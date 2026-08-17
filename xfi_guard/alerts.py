"""Notification policy and Telegram transport for security events."""

from __future__ import annotations

import json
import os
import time
from urllib import request


class AlertManager:
    def __init__(self, token: str | None = None, chat_id: str | None = None, cooldown: int = 300):
        self.token = token or os.getenv("XFI_GUARD_TELEGRAM_TOKEN")
        self.chat_id = chat_id or os.getenv("XFI_GUARD_TELEGRAM_CHAT_ID")
        self.cooldown = max(0, cooldown)
        self._last_sent: dict[str, float] = {}

    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def should_alert(self, event: dict) -> bool:
        if event.get("severity") not in {"warning", "critical"}:
            return False
        fingerprint = str(event.get("fingerprint", ""))
        now = time.monotonic()
        last = self._last_sent.get(fingerprint, 0)
        if now - last < self.cooldown:
            return False
        self._last_sent[fingerprint] = now
        return True

    def send(self, event: dict) -> bool:
        if not self.enabled() or not self.should_alert(event):
            return False
        text = (
            f"XFI Guard [{event.get('severity', 'unknown').upper()}]\\n"
            f"{event.get('event_type', 'security_event')}\\n"
            f"IP: {event.get('ip') or '-'}\\n"
            f"User: {event.get('user') or '-'}\\n"
            f"{event.get('message', '')}"
        )
        analysis = event.get("ai_analysis")
        if analysis:
            text += f"\\n\\n🤖 Gemini analysis:\\n{analysis}"
        text = text[:3900]
        payload = json.dumps({"chat_id": self.chat_id, "text": text}).encode()
        req = request.Request(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=10) as response:
                return 200 <= response.status < 300
        except Exception:
            return False
