"""Local encrypted-at-rest-ready storage for AI provider settings.

The store intentionally keeps API keys outside Git. File permissions are restricted to the owner.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_PATH = "/var/lib/xfi-guard/ai.json"
DEFAULT_GEMINI_MODEL = "gemini-3.1-pro-preview"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"


def load(path: str = DEFAULT_PATH) -> dict:
    p = Path(path)
    if not p.is_file():
        return {
            "provider": "gemini",
            "gemini_model": DEFAULT_GEMINI_MODEL,
            "groq_model": DEFAULT_GROQ_MODEL,
            "gemini_key": "",
            "groq_key": "",
        }
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        data.setdefault("provider", "gemini")
        data.setdefault("gemini_model", DEFAULT_GEMINI_MODEL)
        data.setdefault("groq_model", DEFAULT_GROQ_MODEL)
        data.setdefault("gemini_key", "")
        data.setdefault("groq_key", "")
        return data
    except (OSError, json.JSONDecodeError):
        return {}


def save(data: dict, path: str = DEFAULT_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(p, 0o600)
