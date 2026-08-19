"""Telegram UI for registering and testing 3X-UI API endpoints."""
from __future__ import annotations

import asyncio
import os
import re
from urllib.parse import urlparse

from aiogram import F, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .xui_api_store import load, remove, upsert
from .xui_inbounds import XUIClient


class XUIStates(StatesGroup):
    name = State()
    url = State()
    token = State()
    remove_name = State()


def _admin(message) -> bool:
    ids = {int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if v.strip().isdigit()}
    return bool(message.from_user and message.from_user.id in ids)


def _kb(rows):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
    )


def _mask(token: str) -> str:
    if not token:
        return "не задан"
    return token[:4] + "…" + token[-4:] if len(token) >= 10 else "задан"


def xui_menu():
    return _kb([
        ["➕ Добавить 3X-UI", "📋 Список 3X-UI"],
        ["🧪 Проверить 3X-UI", "🗑 Удалить 3X-UI"],
        ["⬅️ Главное меню"],
    ])


def _safe_name(value: str) -> bool:
    return bool(re.fullmatch(r"[\w .:@/-]{1,80}", value, re.UNICODE))


def _normalize_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL должен начинаться с http:// или https:// и содержать адрес панели")
    for suffix in ("/panel/api/inbounds/list", "/panel/api"):
        if value.endswith(suffix):
            value = value[: -len(suffix)].rstrip("/")
            break
    return value


def install_xui_handlers(dp: Dispatcher) -> None:
    if getattr(dp, "_xfi_xui_ui_installed", False):
        return
    dp._xfi_xui_ui_installed = True

    @dp.message(F.text == "⚙️ 3X-UI")
    async def xui_button(m, state: FSMContext):
        if _admin(m):
            await state.clear()
            await m.answer("⚙️ 3X-UI\n\nУправление API-подключениями 3X-UI.", reply_markup=xui_menu())

    @dp.message(F.text == "➕ Добавить 3X-UI")
    async def add_prompt(m, state: FSMContext):
        if _admin(m):
            await state.set_state(XUIStates.name)
            await m.answer("Введите имя узла 3X-UI, например: Germany", reply_markup=_kb([["❌ Отмена"], ["⬅️ Главное меню"]]))

    @dp.message(XUIStates.name)
    async def add_name(m, state: FSMContext):
        if not _admin(m): return
        if m.text in {"❌ Отмена", "⬅️ Главное меню"}:
            await state.clear(); await m.answer("Отменено.", reply_markup=xui_menu()); return
        name = (m.text or "").strip()
        if not _safe_name(name):
            await m.answer("❌ Недопустимое имя. Используйте до 80 символов: буквы, цифры, пробел, . : @ / - _")
            return
        await state.update_data(name=name)
        await state.set_state(XUIStates.url)
        await m.answer("Введите URL панели 3X-UI, например https://panel.example.com\nМожно вставить полный URL панели — /panel/api будет добавлен автоматически.")

    @dp.message(XUIStates.url)
    async def add_url(m, state: FSMContext):
        if not _admin(m): return
        if m.text in {"❌ Отмена", "⬅️ Главное меню"}:
            await state.clear(); await m.answer("Отменено.", reply_markup=xui_menu()); return
        try:
            url = _normalize_url(m.text or "")
        except ValueError as exc:
            await m.answer(f"❌ {exc}")
            return
        await state.update_data(url=url)
        await state.set_state(XUIStates.token)
        await m.answer("Введите API Bearer token 3X-UI. Если авторизация не требуется, отправьте: -")

    @dp.message(XUIStates.token)
    async def add_token(m, state: FSMContext):
        if not _admin(m): return
        if m.text in {"❌ Отмена", "⬅️ Главное меню"}:
            await state.clear(); await m.answer("Отменено.", reply_markup=xui_menu()); return
        data = await state.get_data()
        token = "" if (m.text or "").strip() == "-" else (m.text or "").strip()
        try:
            item = upsert(data["name"], data["url"], token)
            result = await asyncio.to_thread(_test_item, item)
        except Exception as exc:
            await state.clear()
            await m.answer(f"❌ Не удалось сохранить 3X-UI: {type(exc).__name__}: {exc}", reply_markup=xui_menu())
            return
        await state.clear()
        if result["ok"]:
            test_line = f"\n\n🟢 API доступен, inbounds: {result['count']}"
        else:
            test_line = f"\n\n🟠 Сохранено, но проверка API не прошла: {result['error']}"
        await m.answer(
            f"✅ 3X-UI сохранён\n\nИмя: {item['name']}\nURL: {item['url']}\nToken: {_mask(item['token'])}{test_line}",
            reply_markup=xui_menu(),
        )

    @dp.message(F.text == "📋 Список 3X-UI")
    async def list_xui(m):
        if not _admin(m): return
        items = load()
        if not items:
            await m.answer("📋 Подключений 3X-UI пока нет.", reply_markup=xui_menu()); return
        lines = [f"• {x['name']} — {x['url']} — token: {_mask(x.get('token', ''))}" for x in items]
        await m.answer("📋 Подключения 3X-UI\n\n" + "\n".join(lines), reply_markup=xui_menu())

    @dp.message(F.text == "🧪 Проверить 3X-UI")
    async def test_all(m):
        if not _admin(m): return
        items = load()
        if not items:
            await m.answer("❌ Сначала добавьте API 3X-UI.", reply_markup=xui_menu()); return
        lines = []
        for item in items:
            result = await asyncio.to_thread(_test_item, item)
            if result["ok"]:
                lines.append(f"✅ {item['name']}: API отвечает, inbounds={result['count']}")
            else:
                lines.append(f"❌ {item['name']}: {result['error']}")
        await m.answer("🧪 Проверка 3X-UI\n\n" + "\n".join(lines), reply_markup=xui_menu())

    @dp.message(F.text == "🗑 Удалить 3X-UI")
    async def remove_prompt(m, state: FSMContext):
        if _admin(m):
            await state.set_state(XUIStates.remove_name)
            await m.answer("Введите точное имя подключения для удаления:", reply_markup=_kb([["❌ Отмена"], ["⬅️ Главное меню"]]))

    @dp.message(XUIStates.remove_name)
    async def remove_item(m, state: FSMContext):
        if not _admin(m): return
        if m.text in {"❌ Отмена", "⬅️ Главное меню"}:
            await state.clear(); await m.answer("Отменено.", reply_markup=xui_menu()); return
        name = (m.text or "").strip()
        changed = remove(name)
        await state.clear()
        await m.answer("✅ Подключение удалено." if changed else "❌ Подключение не найдено.", reply_markup=xui_menu())


def _test_item(item: dict) -> dict:
    client = XUIClient(item["url"], item.get("token") or None, timeout=8)
    status, body = client.list_inbounds()
    success = status < 300 and bool(body.get("success", True))
    return {"ok": success, "count": len(body.get("obj") or []) if success else 0, "status": status, "error": body.get("msg", f"HTTP {status}") if not success else ""}
