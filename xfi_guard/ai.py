"""Unified AI provider interface for XFI Guard."""

from __future__ import annotations

import json
import os
from urllib import request

from .gemini import GeminiAnalyzer


class AIAnalyzer:
    def __init__(self, provider: str | None = None):
        self.provider = (provider or os.getenv("XFI_GUARD_AI_PROVIDER", "gemini")).lower()
        self.gemini = GeminiAnalyzer()

    def enabled(self) -> bool:
        if self.provider == "gemini":
            return self.gemini.enabled()
        if self.provider == "groq":
            return bool(os.getenv("XFI_GUARD_GROQ_API_KEY") or os.getenv("GROQ_API_KEY"))
        return False

    def analyze(self, event: dict) -> str | None:
        if self.provider == "gemini":
            return self.gemini.analyze(event)
        if self.provider != "groq" or not self.enabled():
            return None
        key = os.getenv("XFI_GUARD_GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
        model = os.getenv("XFI_GUARD_GROQ_MODEL", "llama-3.3-70b-versatile")
        prompt = "Analyze this VPS security event. Return concise JSON with risk, explanation, recommended_action. Do not execute commands.\n" + json.dumps(event, ensure_ascii=False)
        body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
        req = request.Request("https://api.groq.com/openai/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}, method="POST")
        try:
            with request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode())
            return payload["choices"][0]["message"]["content"]
        except Exception:
            return None
