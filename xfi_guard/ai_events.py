"""Безопасный журнал переключений AI-провайдеров."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Lock

DEFAULT_PATH = "/var/lib/xfi-guard/ai-events.jsonl"
_lock = Lock()


def record(event: dict, path: str | None = None) -> None:
    """Append a small, secret-free AI runtime event without breaking analysis."""
    target = Path(path or os.getenv("XFI_GUARD_AI_EVENTS_PATH", DEFAULT_PATH))
    payload = {"ts": int(time.time()), **event}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with target.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    except OSError:
        # Audit logging must never make security analysis unavailable.
        return
