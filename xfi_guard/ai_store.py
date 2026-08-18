"""Local storage for AI provider settings."""
from __future__ import annotations
import json, os
from pathlib import Path
DEFAULT_PATH="/var/lib/xfi-guard/ai.json"
DEFAULT_GEMINI_MODEL="gemini-2.5-flash"
DEFAULT_GROQ_MODEL="openai/gpt-oss-20b"
DEFAULT_OPENROUTER_MODEL="openai/gpt-oss-20b"

def load(path: str=DEFAULT_PATH)->dict:
    p=Path(path); defaults={"provider":"gemini","gemini_model":DEFAULT_GEMINI_MODEL,"groq_model":DEFAULT_GROQ_MODEL,"openrouter_model":DEFAULT_OPENROUTER_MODEL,"openrouter_models":[],"gemini_key":"","groq_key":"","openrouter_key":"","ai_weights":{"gemini":1.0,"groq":1.0,"openrouter":1.0},"ai_min_consensus":0.60,"ai_timeout":20,"ai_max_workers":6,"ai_cooldown":30}
    if not p.is_file(): return defaults
    try:
        data=json.loads(p.read_text(encoding="utf-8"));
        if not isinstance(data,dict): return defaults
        for k,v in defaults.items(): data.setdefault(k,v)
        return data
    except (OSError,json.JSONDecodeError): return defaults

def save(data:dict,path:str=DEFAULT_PATH)->None:
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8"); os.chmod(p,0o600)
