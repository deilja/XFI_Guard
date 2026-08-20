"""Telegram alert delivery for autonomous Security Monitor."""
from __future__ import annotations
import json
import os
from urllib import error, request

API = "https://api.telegram.org/bot{token}/{method}"


def _token() -> str:
    return os.getenv("XFI_GUARD_BOT_TOKEN", "")


def _admins() -> list[int]:
    return [int(x) for x in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if x.strip().isdigit()]


def _call(method: str, payload: dict) -> dict:
    token = _token()
    if not token:
        return {"ok": False, "description": "XFI_GUARD_BOT_TOKEN not configured"}
    req = request.Request(API.format(token=token, method=method), data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode())
    except (OSError, error.HTTPError, ValueError) as exc:
        return {"ok": False, "description": f"Telegram error: {type(exc).__name__}: {exc}"}


def format_alert(alert: dict) -> str:
    consensus = alert.get("consensus") or {}
    verdicts = consensus.get("verdicts") or []
    lines = [
        "🚨 XFI GUARD — ОБНАРУЖЕНА УГРОЗА", "",
        f"IP: {alert.get('ip', '-')}",
        f"Risk Score: {alert.get('score', 0)}/100",
        f"Risk: {str(alert.get('risk', 'unknown')).upper()}",
        f"AI: {consensus.get('providers_used', 0)} провайдеров / {consensus.get('models_used', 0)} моделей",
        f"Консенсус: {'ДА' if consensus.get('consensus') else 'НЕТ'}",
        f"Уверенность: {float(consensus.get('confidence', 0) or 0):.0%}",
        "",
    ]
    for v in verdicts[:3]:
        provider = v.get("provider", "?")
        risk = str(v.get("risk", "unknown")).upper()
        confidence = float(v.get("confidence", 0) or 0)
        reason = str(v.get("reason", "")).replace("\n", " ")[:450]
        lines.append(f"• {provider}: {risk}, {confidence:.0%}")
        if reason:
            lines.append(f"  {reason}")
    if not verdicts:
        lines.append("⚠️ AI-вердикт не получен; угроза определена локальным анализатором.")
    return "\n".join(lines)[:3900]


def send_alert(alert: dict) -> list[dict]:
    text = format_alert(alert)
    ip = str(alert.get("ip", "")).strip()
    score = int(alert.get("score", 0) or 0)
    risk = str(alert.get("risk", "unknown")).lower()
    rows = []
    if ip:
        rows.append([{"text": "🛡 Заблокировать IP", "callback_data": "xfi:block:" + ip}, {"text": "🔎 Подробнее", "callback_data": "xfi:detail:" + str(alert.get("id", ""))}])
    else:
        rows.append([{"text": "🔎 Подробнее", "callback_data": "xfi:detail:" + str(alert.get("id", ""))}])
    if risk == "critical" or score >= 80:
        rows.append([{"text": "🚨 Заблокировать все критические", "callback_data": "xfi:block_all_critical"}])
    rows.append([{"text": "🔕 Игнорировать", "callback_data": "xfi:ignore:" + str(alert.get("id", ""))}])
    markup = {"inline_keyboard": rows}
    results=[]
    for chat_id in _admins():
        result=_call("sendMessage", {"chat_id": chat_id, "text": text, "reply_markup": markup})
        results.append(result)
        if not result.get("ok"):
            print(f"Telegram alert delivery failed for chat {chat_id}: {result.get('description', 'unknown error')}", flush=True)
    return results
