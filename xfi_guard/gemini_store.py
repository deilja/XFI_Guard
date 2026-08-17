"""Protected local storage for Gemini API settings."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

DEFAULT_MODEL = "gemini-2.5-pro"
DEFAULT_PATH = "/var/lib/xfi-guard/gemini.json"


def load(path: str | Path = DEFAULT_PATH) -> dict[str, str]:
    target = Path(path)
    if not target.is_file():
        return {"api_key": "", "model": DEFAULT_MODEL}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return {"api_key": str(data.get("api_key", "")), "model": str(data.get("model", DEFAULT_MODEL)) or DEFAULT_MODEL}
    except (OSError, json.JSONDecodeError):
        return {"api_key": "", "model": DEFAULT_MODEL}


def save(api_key: str, model: str, path: str | Path = DEFAULT_PATH) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps({"api_key": api_key.strip(), "model": model.strip() or DEFAULT_MODEL}, indent=2), encoding="utf-8")
    os.chmod(temp, stat.S_IRUSR | stat.S_IWUSR)
    temp.replace(target)
    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
