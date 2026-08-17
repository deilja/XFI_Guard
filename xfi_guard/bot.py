"""Telegram admin bot for XFI Guard. Интерфейс бота на русском языке."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
from urllib import request

from .ai import AIAnalyzer
from .ai_store import load as load_ai, save as save_ai
from .checks import collect_basic_checks
from .events import parse_file
from .attack_surface import collect_attack_surface
from .security import collect_security_checks
from .security_center import ai_report, summarize
from .vpn import collect_vpn_checks
from .firewall import block_ip, unblock_ip, list_blocked_ips, validate_public_ip
from .gemini import normalize_model

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


TOKEN = os.getenv("XFI_GUARD_BOT_TOKEN")
ADMIN_IDS = {
    int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",")
    if v.strip().isdigit()
}

GROQ_MODELS = [
    ("🧠 GPT-OSS 120B", "openai/gpt-oss-120b"),
    ("🧠 GPT-OSS 20B", "openai/gpt-oss-20b"),
    ("🦙 Llama 3.3 70B", "llama-3.3-70b-versatile"),
    ("⚡ Llama 3.1 8B", "llama-3.1-8b-instant"),
    ("🌐 Groq Compound", "groq/compound"),
    ("🚀 Groq Compound Mini", "groq/compound-mini"),
]

GEMINI_MODELS = [
    ("🧠 Gemini 3.1 Pro", "gemini-3.1-pro-preview"),
    ("⚡ Gemini 3.6 Flash", "gemini-3.6-flash"),
    ("⚡ Gemini 3.5 Flash", "gemini-3.5-flash"),
    ("🚀 Gemini 3.5 Flash Lite", "gemini-3.5-flash-lite"),
    ("⚡ Gemini 3.1 Flash Lite", "gemini-3.1-flash-lite"),
    ("🌐 Gemini 3 Flash Preview", "gemini-3-flash-preview"),
    ("🧠 Gemini 2.5 Pro", "gemini-2.5-pro"),
    ("⚡ Gemini 2.5 Flash", "gemini-2.5-flash"),
]


class SetupStates(StatesGroup):
    provider = State()
    gemini_key = State()
    groq_key = State()
    gemini_model = State()
    groq_model = State()
    block_ip = State()
    confirm_block = State()
    unblock_ip = State()


def admin(m):
    return bool(m.from_user and m.from_user.id in ADMIN_IDS)


def mask(k):
    return k[:4] + "…" + k[-4:] if len(k) >= 8 else ("настроен" if k else "не настроен")


def kb(rows):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
    )


def main_kb():
    return kb([
        ["📊 Статус", "🔐 Безопасность"],
        ["🛡 Fail2Ban", "🔥 UFW"],
        ["🌐 VPN/Xray", "📋 События"],
        ["🛡 Картина атак", "🤖 AI"],
        ["🧠 Центр AI", "🚫 Блокировка IP"],
        ["🔄 Проверить сейчас", "❓ Помощь"],
    ])


def ai_kb():
    return kb([
        ["🟢 Gemini", "🔵 Groq"],
        ["🔀 Выбрать AI"],
        ["🔑 Ключ Gemini", "🔑 Ключ Groq"],
        ["🧠 Модель Gemini", "🧠 Модель Groq"],
        ["📋 Модели Gemini", "📋 Модели Groq"],
        ["✏️ Своя модель Gemini", "✏️ Своя модель Groq"],
        ["🧪 Проверить AI", "ℹ️ Статус AI"],
        ["⬅️ Главное меню"],
    ])


def gemini_models_kb():
    rows = [[x[0] for x in GEMINI_MODELS[i:i + 2]] for i in range(0, len(GEMINI_MODELS), 2)]
    rows += [["🔄 Получить модели Gemini API"], ["✏️ Своя модель Gemini"], ["⬅️ AI"]]
    return kb(rows)


def groq_models_kb():
    rows = [[x[0] for x in GROQ_MODELS[i:i + 2]] for i in range(0, len(GROQ_MODELS), 2)]
    rows += [["🔄 Получить модели Groq API"], ["✏️ Своя модель Groq"], ["⬅️ AI"]]
    return kb(rows)


def center_kb():
    return kb([
        ["📊 Анализ за 24 часа"], ["🚨 Топ атакующих IP"], ["🤖 AI-анализ сводки"],
        ["🤖 Рекомендации блокировки"], ["🔄 Обновить"], ["⬅️ Главное меню"],
    ])


def block_kb():
    return kb([
        ["🤖 Рекомендации AI"], ["📋 Выбрать IP из событий"], ["✏️ Ввести IP вручную"],
        ["📋 Заблокированные IP", "🔓 Разблокировать IP"], ["⬅️ Главное меню"],
    ])


def confirm_kb():
    return kb([["✅ Подтвердить блокировку"], ["❌ Отмена"]])


def results(r):
    return "\n".join(
        f"{getattr(x, 'status', 'unknown').upper()}: {x.name} — {x.message}"
        for x in r
    )[:3800] or "Нет данных."


def events():
    from .config import load_config
    c = load_config()
    return parse_file(c.ssh_log, "ssh") + parse_file(c.fail2ban_log, "fail2ban")


def active_events():
    """События только по ещё не заблокированным IP."""
    blocked = {str(ip).strip() for ip in list_blocked_ips()}
    return [
        e for e in events()
        if not getattr(e, "ip", None) or str(e.ip).strip() not in blocked
    ]


def event_dicts():
    return [
        {
            "timestamp": getattr(e, "timestamp", ""),
            "severity": getattr(e, "severity", "unknown"),
            "event_type": getattr(e, "event_type", "unknown"),
            "ip": getattr(e, "ip", None),
            "user": getattr(e, "user", None),
            "message": getattr(e, "message", ""),
        }
        for e in active_events()
    ]


def attack_surface_text():
    data = collect_attack_surface()
    blocked = {str(i).strip() for i in list_blocked_ips()}
    items = [x for x in data.get("ips", []) if str(x.get("ip", "")).strip() not in blocked]
    lines = [
        "🛡 Полная картина атак за текущий период",
        "",
        f"Fail2Ban: {data.get('fail2ban_count', 0)}",
        f"UFW DENY/REJECT: {data.get('ufw_count', 0)}",
        f"SSH неудачных входов: {data.get('ssh_count', 0)}",
        f"Уникальных активных IP: {len(items)}",
        "",
    ]
    for x in items[:15]:
        lines.append(
            f"• {x['ip']} — {x['risk']} ({x['risk_score']}/100) | "
            f"источники: {', '.join(x['sources'])} | событий: {x['events']}"
        )
        if x.get("jails"):
            lines.append(f"  Jail: {', '.join(x['jails'])}")
        if x.get("reason"):
            lines.append(f"  Причина: {x['reason'][:180]}")
    return "\n".join(lines)[:3900]


def fetch_groq_models(key):
    req = request.Request(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read().decode())
    return sorted({
        str(x.get("id")) for x in data.get("data", [])
        if x.get("id") and not str(x.get("id")).startswith("whisper")
    })


def fetch_gemini_models(key):
    req = request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read().decode())
    models = []
    for item in data.get("models", []):
        name = str(item.get("name", ""))
        model_id = name.removeprefix("models/")
        methods = item.get("supportedGenerationMethods", []) or []
        if (
            model_id.startswith("gemini-")
            and "generateContent" in methods
            and not any(x in model_id.lower() for x in ("image", "tts", "embedding", "robotics"))
        ):
            models.append(model_id)
    return sorted(set(models))


def build_dispatcher():
    """Создать и вернуть Dispatcher. Никаких сетевых вызовов при импорте."""
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message(Command("start"))
    async def start(m, state):
        await state.clear()
        if admin(m):
            await m.answer(
                "🛡 XFI Guard\n\nПанель управления сервером. Выберите функцию:",
                reply_markup=main_kb(),
            )

    @dp.message(Command("status"))
    async def status_command(m):
        if admin(m):
            await m.answer(
                "📊 Статус XFI Guard\n\n" + results(
                    collect_basic_checks() + collect_security_checks() + collect_vpn_checks()
                ),
                reply_markup=main_kb(),
            )

    @dp.message(F.text == "📊 Статус")
    async def status(m):
        await status_command(m)

    @dp.message(F.text == "🔐 Безопасность")
    async def security(m):
        if admin(m):
            await m.answer("🔐 Безопасность\n\n" + results(collect_security_checks()), reply_markup=main_kb())

    @dp.message(Command("security"))
    async def security_command(m):
        await security(m)

    @dp.message(F.text == "🛡 Fail2Ban")
    async def fail2ban(m):
        if admin(m):
            await m.answer(
                "🛡 Fail2Ban\n\n" + results([x for x in collect_security_checks() if x.name == "fail2ban"]),
                reply_markup=main_kb(),
            )

    @dp.message(F.text == "🔥 UFW")
    async def ufw(m):
        if admin(m):
            await m.answer(
                "🔥 UFW\n\n" + results([x for x in collect_security_checks() if x.name == "ufw"]),
                reply_markup=main_kb(),
            )

    @dp.message(F.text == "🌐 VPN/Xray")
    async def vpn(m):
        if admin(m):
            await m.answer("🌐 VPN/Xray\n\n" + results(collect_vpn_checks()), reply_markup=main_kb())

    @dp.message(F.text == "📋 События")
    async def ev(m):
        if admin(m):
            e = active_events()[-20:]
            text = "\n".join(
                f"{x.severity.upper()} | {x.event_type} | {x.ip or '-'} | {x.user or '-'}"
                for x in e
            ) or "Нет активных событий. Заблокированные IP скрыты из списка."
            await m.answer("📋 Последние события\n\n" + text, reply_markup=main_kb())

    @dp.message(F.text == "🛡 Картина атак")
    async def attack_surface(m):
        if admin(m):
            await m.answer(attack_surface_text(), reply_markup=main_kb())

    @dp.message(F.text == "🔄 Проверить сейчас")
    async def check(m):
        if admin(m):
            await m.answer(
                "🔄 Проверка завершена\n\n" + results(
                    collect_basic_checks() + collect_security_checks() + collect_vpn_checks()
                ),
                reply_markup=main_kb(),
            )

    @dp.message(F.text == "🚫 Блокировка IP")
    async def block_menu(m, state):
        if admin(m):
            await state.clear()
            await m.answer(
                "🚫 Управление блокировками IP\n\n"
                "ИИ видит Fail2Ban + UFW + SSH и только рекомендует адреса. "
                "Блокировка выполняется только после вашего подтверждения.",
                reply_markup=block_kb(),
            )

    @dp.message(F.text == "🤖 Рекомендации AI")
    async def ai_recommendations(m, state):
        if not admin(m):
            return
        await state.clear()
        await m.answer("🤖 Анализ полной картины атак: SSH + Fail2Ban + UFW...", reply_markup=block_kb())
        recs = AIAnalyzer().recommend_block_ips(event_dicts())
        if not recs:
            await m.answer("❌ AI не дал рекомендаций. Проверьте AI, SSH-события, Fail2Ban и UFW.", reply_markup=block_kb())
            return
        for r in recs:
            await m.answer(
                f"🚨 Рекомендация AI\n\nIP: {r['ip']}\n"
                f"Риск: {r.get('risk', 'medium').upper()}\n"
                f"Уверенность: {r['confidence']:.0%}\nПричина: {r['reason']}",
                reply_markup=kb([[f"🚫 Заблокировать {r['ip']}"], ["⬅️ Главное меню"]]),
            )

    @dp.message(F.text == "📋 Выбрать IP из событий")
    async def choose_event_ip(m, state):
        if not admin(m):
            return
        counts = {}
        for e in active_events():
            ip = getattr(e, "ip", None)
            if ip:
                try:
                    validate_public_ip(ip)
                except ValueError:
                    continue
                counts[ip] = counts.get(ip, 0) + 1
        if not counts:
            await m.answer("Нет активных публичных IPv4 в событиях. Уже заблокированные адреса не показываются.", reply_markup=block_kb())
            return
        rows = [[f"🌐 {ip} — {n} событий"] for ip, n in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:20]]
        rows.append(["⬅️ Главное меню"])
        await m.answer("📋 Выберите IP для блокировки:", reply_markup=kb(rows))

    @dp.message(F.text.startswith("🌐 "))
    async def event_ip_button(m, state):
        if not admin(m):
            return
        parts = (m.text or "").split()
        if len(parts) < 2:
            return
        ip = parts[1]
        try:
            ip = validate_public_ip(ip)
        except ValueError:
            await m.answer("❌ Некорректный IP.", reply_markup=block_kb())
            return
        await state.update_data(block_ip=ip, source="events")
        await state.set_state(SetupStates.confirm_block)
        await m.answer(
            f"⚠️ Подтвердите блокировку\n\nIP: {ip}\n\nUFW добавит DENY для этого адреса.",
            reply_markup=confirm_kb(),
        )

    @dp.message(F.text == "✏️ Ввести IP вручную")
    async def manual_block(m, state):
        if admin(m):
            await state.set_state(SetupStates.block_ip)
            await m.answer("Введите публичный IPv4 для блокировки, например 203.0.113.10:", reply_markup=kb([["❌ Отмена"]]))

    @dp.message(SetupStates.block_ip)
    async def receive_block_ip(m, state):
        if not admin(m):
            return
        if m.text == "❌ Отмена":
            await state.clear()
            await m.answer("Отменено.", reply_markup=block_kb())
            return
        try:
            ip = validate_public_ip(m.text or "")
        except ValueError as exc:
            await m.answer(f"❌ {exc}")
            return
        await state.update_data(block_ip=ip)
        await state.set_state(SetupStates.confirm_block)
        await m.answer(f"⚠️ Подтвердите блокировку\n\nIP: {ip}", reply_markup=confirm_kb())

    @dp.message(F.text.startswith("🚫 Заблокировать "))
    async def recommended_block_button(m, state):
        if not admin(m):
            return
        ip = (m.text or "").removeprefix("🚫 Заблокировать ").strip()
        try:
            ip = validate_public_ip(ip)
        except ValueError:
            await m.answer("❌ Некорректный IP.", reply_markup=block_kb())
            return
        await state.update_data(block_ip=ip)
        await state.set_state(SetupStates.confirm_block)
        await m.answer(
            f"⚠️ AI рекомендует проверить этот адрес перед блокировкой.\n\nIP: {ip}\n\nБлокировать?",
            reply_markup=confirm_kb(),
        )

    @dp.message(SetupStates.confirm_block, F.text == "✅ Подтвердить блокировку")
    async def confirm_block(m, state):
        if not admin(m):
            return
        data = await state.get_data()
        ip = data.get("block_ip")
        try:
            ok, msg = block_ip(ip)
        except ValueError as exc:
            ok, msg = False, str(exc)
        await state.clear()
        await m.answer(("✅ " if ok else "❌ ") + msg, reply_markup=block_kb())

    @dp.message(SetupStates.confirm_block, F.text == "❌ Отмена")
    async def cancel_block(m, state):
        await state.clear()
        await m.answer("❌ Блокировка отменена.", reply_markup=block_kb())

    @dp.message(F.text == "📋 Заблокированные IP")
    async def blocked(m):
        if not admin(m):
            return
        ips = list_blocked_ips()
        text = "\n".join(f"• {ip}" for ip in ips) if ips else "Нет адресов."
        await m.answer("📋 Заблокированные публичные IP:\n\n" + text, reply_markup=block_kb())

    @dp.message(F.text == "🔓 Разблокировать IP")
    async def choose_unblock(m, state):
        if not admin(m):
            return
        ips = list_blocked_ips()
        if not ips:
            await m.answer("Нет заблокированных публичных IP.", reply_markup=block_kb())
            return
        await state.set_state(SetupStates.unblock_ip)
        await m.answer(
            "Выберите IP для разблокировки:",
            reply_markup=kb([[f"🔓 {ip}"] for ip in ips[:20]] + [["❌ Отмена"]]),
        )

    @dp.message(SetupStates.unblock_ip)
    async def do_unblock(m, state):
        if not admin(m):
            return
        if m.text == "❌ Отмена":
            await state.clear()
            await m.answer("Отменено.", reply_markup=block_kb())
            return
        ip = (m.text or "").removeprefix("🔓 ").strip()
        try:
            ip = validate_public_ip(ip)
            ok, msg = unblock_ip(ip)
        except ValueError as exc:
            ok, msg = False, str(exc)
        await state.clear()
        await m.answer(("✅ " if ok else "❌ ") + msg, reply_markup=block_kb())

    @dp.message(F.text == "⬅️ Главное меню")
    async def back_main(m, state):
        if admin(m):
            await state.clear()
            await m.answer("🏠 Главное меню", reply_markup=main_kb())

    @dp.message(F.text == "❓ Помощь")
    async def help_menu(m):
        if admin(m):
            await m.answer(
                "❓ XFI Guard\n\n"
                "Бот показывает состояние VPS, SSH/Fail2Ban/UFW-события, "
                "AI-рекомендации и позволяет вручную подтвердить блокировку IP.",
                reply_markup=main_kb(),
            )

    # Минимальная AI-навигация, чтобы кнопка из главного меню всегда отвечала.
    @dp.message(F.text == "🤖 AI")
    async def ai_menu(m, state):
        if admin(m):
            await state.clear()
            await m.answer("🤖 Центр AI\n\nВыберите провайдера или настройку:", reply_markup=ai_kb())

    @dp.message(F.text == "🧠 Центр AI")
    async def ai_center(m, state):
        if admin(m):
            await state.clear()
            await m.answer("🧠 Центр AI\n\nСводка безопасности и рекомендации:", reply_markup=center_kb())

    @dp.message(F.text == "📊 Анализ за 24 часа")
    async def center_summary(m):
        if admin(m):
            await m.answer("📊 Анализ за 24 часа\n\n" + summarize(), reply_markup=center_kb())

    @dp.message(F.text == "🚨 Топ атакующих IP")
    async def center_top(m):
        if admin(m):
            await m.answer(attack_surface_text(), reply_markup=center_kb())

    @dp.message(F.text == "🤖 AI-анализ сводки")
    async def center_ai(m):
        if admin(m):
            report = ai_report()
            await m.answer("🤖 AI-анализ\n\n" + (report or "AI не вернул ответ."), reply_markup=center_kb())

    @dp.message(F.text == "🤖 Рекомендации блокировки")
    async def center_recommend(m, state):
        if admin(m):
            await state.clear()
            await ai_recommendations(m, state)

    @dp.message(F.text == "🔄 Обновить")
    async def center_refresh(m):
        if admin(m):
            await m.answer(attack_surface_text(), reply_markup=center_kb())

    return dp


async def main():
    token = os.getenv("XFI_GUARD_BOT_TOKEN")
    if not token:
        raise RuntimeError("XFI_GUARD_BOT_TOKEN не задан")
    bot = Bot(token=token)
    dp = build_dispatcher()
    print("XFI Guard Bot: polling запущен", flush=True)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
