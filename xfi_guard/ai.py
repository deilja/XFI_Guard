"""Unified AI provider interface for XFI Guard."""

from __future__ import annotations

import json
import os
from urllib import request

from .gemini import GeminiAnalyzer
from .ai_store import load


class AIAnalyzer:
    def __init__(self, provider: str | None = None):
        cfg = load()
        self.provider = (provider or cfg.get("provider") or os.getenv("XFI_GUARD_AI_PROVIDER", "gemini")).lower()
        self.gemini = GeminiAnalyzer(api_key=cfg.get("gemini_key") or None, model=cfg.get("gemini_model") or None)
        self.groq_key = cfg.get("groq_key") or os.getenv("XFI_GUARD_GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
        self.groq_model = cfg.get("groq_model") or os.getenv("XFI_GUARD_GROQ_MODEL", "llama-3.3-70b-versatile")

    def enabled(self) -> bool:
        return self.gemini.enabled() if self.provider == "gemini" else self.provider == "groq" and bool(self.groq_key)

    def analyze(self, event: dict) -> str | None:
        if self.provider == "gemini":
            return self.gemini.analyze(event)
        if self.provider != "groq" or not self.groq_key:
            return None
        prompt = "Analyze this VPS security event. Return concise JSON with risk, explanation, recommended_action. Do not execute commands.\n" + json.dumps(event, ensure_ascii=False)
        body = {"model": self.groq_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
        req = request.Request("https://api.groq.com/openai/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.groq_key}"}, method="POST")
        try:
            with request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode())
            return payload["choices"][0]["message"]["content"]
        except Exception:
            return None
