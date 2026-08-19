"""Validated persistent storage for AI provider settings."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .ai_config import AISettings

DEFAULT_PATH = "/var/lib/xfi-guard/ai.json"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
DEFAULT_OPENROUTER_MODEL = "openrouter/free"


def load(path: str = DEFAULT_PATH) -> dict:
    defaults = AISettings(
        gemini_model=DEFAULT_GEMINI_MODEL,
        groq_model=DEFAULT_GROQ_MODEL,
        openrouter_model=DEFAULT_OPENROUTER_MODEL,
    )
    p = Path(path)
    if not p.is_file():
        return defaults.model_dump()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return defaults.model_dump()
        merged = {**defaults.model_dump(), **raw}
        return AISettings.model_validate(merged).model_dump()
    except (OSError, json.JSONDecodeError, ValueError):
        return defaults.model_dump()


def save(data: dict, path: str = DEFAULT_PATH) -> None:
    settings = AISettings.model_validate(data)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(p, 0o600)
