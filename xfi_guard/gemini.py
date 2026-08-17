"""Gemini API integration for security-event analysis."""

from __future__ import annotations

import json
import os
from urllib import request

from .gemini_store import DEFAULT_MODEL, load as load_config


MODEL_ALIASES = {
    "gemini 3.1 pro": "gemini-3.1-pro-preview",
    "gemini 3.1 pro preview": "gemini-3.1-pro-preview",
    "gemini-3.1-pro": "gemini-3.1-pro-preview",
    "gemini 3.5 flash": "gemini-3.5-flash",
    "gemini 3.6 flash": "gemini-3.6-flash",
    "gemini 3.5 flash lite": "gemini-3.5-flash-lite",
    "gemini 3.1 flash lite": "gemini-3.1-flash-lite",
    "gemini 3 flash preview": "gemini-3-flash-preview",
    "gemini 2.5 pro": "gemini-2.5-pro",
}


def normalize_model(model: str | None) -> str:
    value = (model or DEFAULT_MODEL).strip()
    return MODEL_ALIASES.get(value.lower(), value)


class GeminiAnalyzer:
    """Analyze XFI Guard events using the configured Gemini model."""

    def __init__(self, api_key: str | None = None, model: str | None = None, config_path: str | None = None):
        stored = load_config(config_path) if config_path else load_config()
        self.api_key = api_key or stored["api_key"] or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model = normalize_model(model or stored["model"] or DEFAULT_MODEL)

    def enabled(self) -> bool:
        return bool(self.api_key)

    def analyze(self, event: dict) -> str | None:
        if not self.enabled():
            return None
        prompt = (
            "Ты аналитик безопасности XFI Guard. Анализируй событие VPS. "
            "Отвечай кратко и только на русском языке. Верни JSON с ключами: risk, explanation, recommended_action. "
            "Не выполняй команды и не рекомендуй автоматически разрушительные действия.\n\n"
            + json.dumps(event, ensure_ascii=False)
        )
        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        req = request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key}, method="POST")
        try:
            with request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            return None
