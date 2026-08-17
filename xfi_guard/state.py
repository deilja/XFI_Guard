"""Small persistent state store for alert fingerprints."""

from __future__ import annotations

import json
from pathlib import Path


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict = {}
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            self._data = {}
            return
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self._data, dict):
                self._data = {}
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def seen(self, fingerprint: str) -> bool:
        return fingerprint in self._data.get("events", {})

    def mark_seen(self, fingerprint: str, timestamp: str) -> None:
        events = self._data.setdefault("events", {})
        events[fingerprint] = timestamp

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)
