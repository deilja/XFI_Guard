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

    def record_ssh_attempt(self, ip: str) -> None:
        """Persist one normalized SSH failure for cross-cycle detection."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO security_events(event_type, ip, description, risk, confidence, attempts) VALUES(?,?,?,?,?,?)",
                ("ssh_auth_failed", ip, "SSH authentication failure", "unknown", 0.0, 1),
            )

    def recent_ssh_attempts(self, ip: str, window_seconds: int = 600) -> int:
        """Return SSH failures seen for an IP during the rolling time window."""
        window_seconds = max(1, int(window_seconds))
        with self._connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) FROM security_events
                   WHERE event_type='ssh_auth_failed' AND ip=?
                   AND timestamp >= datetime('now', ?)""",
                (ip, f"-{window_seconds} seconds"),
            ).fetchone()
        return int(row[0] or 0) if row else 0

    def recent_threats(self, limit: int = 50) -> list[dict]:
        """Return recent automatic-defense records for diagnostics/UI."""
        limit = max(1, min(int(limit), 200))
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT timestamp,event_type,ip,description,risk,confidence,attempts
                   FROM security_events
                   WHERE event_type IN ('auto_block','ssh_ai_check')
                   ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "timestamp": r[0], "event_type": r[1], "ip": r[2],
                "description": r[3], "risk": r[4], "confidence": r[5], "attempts": r[6],
            }
            for r in rows
        ]
