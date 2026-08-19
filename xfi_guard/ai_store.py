"""Local storage for validated AI provider settings."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .ai_config import AIConfig

DEFAULT_PATH="/var/lib/xfi-guard/ai.json"
DEFAULT_GEMINI_MODEL="gemini-2.5-flash"
DEFAULT_GROQ_MODEL="openai/gpt-oss-20b"
DEFAULT_OPENROUTER_MODEL="openai/gpt-oss-20b"


def _defaults() -> dict:
    return AIConfig(
        gemini_model=DEFAULT_GEMINI_MODEL,
        groq_model=DEFAULT_GROQ_MODEL,
        openrouter_model=DEFAULT_OPENROUTER_MODEL,
    ).as_dict()


def load(path: str=DEFAULT_PATH)->dict:
    p=Path(path)
    defaults=_defaults()
    if not p.is_file(): return defaults
    try:
        data=json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data,dict): return defaults
        merged={**defaults,**data}
        # Preserve forward-compatible extra keys while validating known fields.
        return AIConfig.model_validate(merged).as_dict() | {k:v for k,v in data.items() if k not in AIConfig.model_fields}
    except (OSError,json.JSONDecodeError,ValueError):
        return defaults


def save(data:dict,path:str=DEFAULT_PATH)->None:
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    validated=AIConfig.model_validate(data)
    payload=validated.as_dict()
    # Keep forward-compatible application-specific keys used by the bot.
    for key,value in data.items():
        if key not in AIConfig.model_fields:
            payload[key]=value
    p.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8"); os.chmod(p,0o600)
