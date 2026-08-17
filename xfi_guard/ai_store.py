"""Local encrypted-at-rest-ready storage for AI provider settings.

The store intentionally keeps API keys outside Git. File permissions are restricted to the owner.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_PATH = "/var/lib/xfi-guard/ai.json"


def load(path: str = DEFAULT_PATH) -> dict:
    p = Path(path)
    if not p.is_file():
        return {"provider": "gemini", "gemini_model": "gemini-2.5-pro", "groq_model": "llama-3.3-70b-versatile", "gemini_key": "", "groq_key": ""}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save(data: dict, path: str = DEFAULT_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(p, 0o600)
