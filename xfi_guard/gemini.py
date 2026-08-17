"""Gemini API integration for security-event analysis."""

from __future__ import annotations

import json
import os
from urllib import request, error, parse

from .gemini_store import DEFAULT_MODEL, load as load_config

MODEL_ALIASES = {
    "gemini 3.1 pro": "gemini-3.1-pro-preview",
    "gemini 3.1 pro preview": "gemini-3.1-pro-preview",
    "gemini-3.1-pro": "gemini-3.1-pro-preview",
    "gemini 3 pro": "gemini-3.1-pro-preview",
    "gemini 3 pro preview": "gemini-3.1-pro-preview",
    "gemini-3-pro-preview": "gemini-3.1-pro-preview",
    "gemini 3.5 flash": "gemini-3.5-flash",
    "gemini 3.6 flash": "gemini-3.6-flash",
    "gemini 3.5 flash lite": "gemini-3.5-flash-lite",
    "gemini 3.1 flash lite": "gemini-3.1-flash-lite",
    "gemini 3 flash preview": "gemini-3-flash-preview",
    "gemini 2.5 pro": "gemini-2.5-pro",
    "gemini 2.5 flash": "gemini-2.5-flash",
    "gemini 2.5 flash lite": "gemini-2.5-flash-lite",
}

def normalize_model(model: str | None) -> str:
    value = (model or DEFAULT_MODEL).strip()
    return MODEL_ALIASES.get(value.lower(), value)

class GeminiAnalyzer:
    """Analyze XFI Guard events using the Gemini API."""
    def __init__(self, api_key: str | None = None, model: str | None = None, config_path: str | None = None):
        stored = load_config(config_path) if config_path else load_config()
        self.api_key = api_key or stored["api_key"] or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model = normalize_model(model or stored["model"] or DEFAULT_MODEL)
        self.last_error = ""

    def enabled(self) -> bool:
        return bool(self.api_key)

    def analyze(self, event: dict) -> str | None:
        if not self.enabled():
            self.last_error = "API-ключ Gemini не настроен"
            return None
        prompt = (
            "Ты аналитик безопасности XFI Guard. Анализируй событие VPS. "
            "Отвечай кратко и только на русском языке. Верни JSON с ключами: risk, explanation, recommended_action. "
            "Не выполняй команды и не рекомендуй автоматически разрушительные действия.\n\n"
            + json.dumps(event, ensure_ascii=False)
        )
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 700},
        }
        url = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}".format(
            parse.quote(self.model, safe=""), parse.quote(self.api_key, safe="")
        )
        req = request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "XFI-Guard/1.0"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            candidates = payload.get("candidates") or []
            if not candidates:
                feedback = payload.get("promptFeedback") or {}
                self.last_error = f"Gemini не вернул кандидата (модель {self.model}): {feedback or 'пустой ответ'}"
                return None
            parts = ((candidates[0].get("content") or {}).get("parts") or [])
            text = "\n".join(str(p.get("text", "")) for p in parts if p.get("text"))
            if not text:
                self.last_error = f"Gemini вернул ответ без текста: finishReason={candidates[0].get('finishReason', 'unknown')}"
                return None
            return text
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1200]
            try:
                parsed = json.loads(detail)
                err = parsed.get("error", parsed)
                detail = json.dumps({"code": err.get("code"), "status": err.get("status"), "message": err.get("message")}, ensure_ascii=False)
            except Exception:
                pass
            self.last_error = f"Gemini API HTTP {exc.code}, модель {self.model}: {detail}"
            return None
        except Exception as exc:
            self.last_error = f"Gemini {type(exc).__name__}, модель {self.model}: {exc}"
            return None
