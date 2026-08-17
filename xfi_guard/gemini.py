"""Optional Gemini Pro analysis for security events."""

from __future__ import annotations

import json
import os
from urllib import request


class GeminiAnalyzer:
    """Analyze XFI Guard events with Google's Gemini API.

    Credentials are read only from GEMINI_API_KEY / GOOGLE_API_KEY.
    """

    def __init__(self, api_key: str | None = None, model: str = "gemini-2.5-pro"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model = model

    def enabled(self) -> bool:
        return bool(self.api_key)

    def analyze(self, event: dict) -> str | None:
        if not self.enabled():
            return None
        prompt = (
            "You are the security analyst for XFI Guard. Analyze this VPS security event. "
            "Return concise JSON with keys: risk, explanation, recommended_action. "
            "Do not execute commands and do not recommend destructive actions automatically.\n\n"
            + json.dumps(event, ensure_ascii=False)
        )
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        req = request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            return None
