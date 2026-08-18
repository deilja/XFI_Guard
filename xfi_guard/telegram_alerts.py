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
    req = request.Request(API.format(token=token, method=method), data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode())
    except (OSError, error.HTTPError, ValueError) as exc:
        return {"ok": False, "description": f"Telegram error: {type(exc).__name__}: {exc}"}


def format_alert(alert: dict) -> str:
    consensus = alert.get("consensus") or {}
    verdicts = consensus.get("verdicts") or []
    lines = ["🚨 XFI GUARD — ОБНАРУЖЕНА УГРОЗА", "", f"IP: {alert.get('ip', '-')}", f"Risk Score: {alert.get('score', 0)}/100", f"Risk: {str(alert.get('risk', 'unknown')).upper()}", f"AI: {consensus.get('providers_used', 0)} провайдеров", f"Консенсус: {'ДА' if consensus.get('consensus') else 'НЕТ'}", ""]
    for v in verdicts[:3]:
        lines.append(f"• {v.get('provider', '?')}: {str(v.get('verdict', '')).replace(chr(10), ' ')[:500]}")
    return "\n".join(lines)[:3900]


def send_alert(alert: dict) -> list[dict]:
    text = format_alert(alert)
    markup = {"inline_keyboard": [[{"text": "🛡 Заблокировать", "callback_data": "xfi:block:" + str(alert.get("ip", ""))}, {"text": "🔎 Подробнее", "callback_data": "xfi:detail:" + str(alert.get("id", ""))}], [{"text": "🔕 Игнорировать", "callback_data": "xfi:ignore:" + str(alert.get("id", ""))}]]}
    return [_call("sendMessage", {"chat_id": chat_id, "text": text, "reply_markup": markup}) for chat_id in _admins()]
