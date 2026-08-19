"""SQLite audit store for AI security checks and automatic blocks."""
from __future__ import annotations

import sqlite3
from pathlib import Path


class SecurityDB:
    def __init__(self, path: str = "/var/lib/xfi-guard/security.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init(self):
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT NOT NULL,
                ip TEXT,
                description TEXT NOT NULL,
                risk TEXT,
                confidence REAL,
                attempts INTEGER
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_security_events_ip_time ON security_events(ip, timestamp)")

    def log_event(self, event_type: str, ip: str | None, description: str, risk: str, confidence: float, attempts: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO security_events(event_type, ip, description, risk, confidence, attempts) VALUES(?,?,?,?,?,?)",
                (event_type, ip, str(description)[:1000], risk, float(confidence), int(attempts)),
            )
