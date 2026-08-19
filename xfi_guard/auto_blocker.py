"""AI-assisted SSH auto-blocking with conservative safety gates.

The monitor may automatically block only a public IPv4 when enough independent
SSH failures are observed, AI consensus is high/critical, and confidence meets
the configured threshold. Every automatic action is audited in SQLite.
"""
from __future__ import annotations

import ipaddress
import os
from collections import Counter
from pathlib import Path

from .ai import AIAnalyzer
from .auto_defense import confirm_block
from .firewall import list_blocked_ips
from .security_db import SecurityDB


class AutoBlocker:
    def __init__(self, *, enabled: bool = False, confidence: float = 0.90, min_attempts: int = 5, db_path: str = "/var/lib/xfi-guard/security.db"):
        self.enabled = enabled
        self.confidence = max(0.0, min(1.0, float(confidence)))
        self.min_attempts = max(1, int(min_attempts))
        self.ai = AIAnalyzer()
        self.db = SecurityDB(db_path)
        self.whitelist = self._load_whitelist()

    @staticmethod
    def _load_whitelist() -> set[str]:
        raw = os.getenv("XFI_GUARD_AUTO_BLOCK_WHITELIST", "")
        result: set[str] = set()
        for value in raw.split(","):
            value = value.strip()
            if not value:
                continue
            try:
                ip = ipaddress.ip_address(value)
                if ip.version == 4:
                    result.add(ip.compressed)
            except ValueError:
                continue
        return result

    def evaluate(self, events: list[dict]) -> list[dict]:
        """Analyze fresh SSH failures grouped by source IP and optionally block."""
        grouped: dict[str, list[dict]] = {}
        for event in events:
            if event.get("event_type") != "ssh_auth_failed":
                continue
            ip = str(event.get("ip") or "").strip()
            try:
                parsed = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if parsed.version != 4 or not parsed.is_global or parsed.compressed in self.whitelist:
                continue
            grouped.setdefault(parsed.compressed, []).append(event)

        blocked = set(list_blocked_ips())
        results: list[dict] = []
        for ip, items in grouped.items():
            attempts = len(items)
            if attempts < self.min_attempts or ip in blocked:
                continue
            analysis = self.ai.analyze_consensus({
                "event_type": "ssh_bruteforce",
                "ip": ip,
                "failed_attempts": attempts,
                "events": items,
            })
            risk = str(analysis.get("winner", "unknown")).lower()
            confidence = float(analysis.get("confidence", 0) or 0)
            decision = {
                "ip": ip,
                "attempts": attempts,
                "risk": risk,
                "confidence": confidence,
                "consensus": bool(analysis.get("consensus")),
                "providers": analysis.get("providers", []),
                "reason": next((x.get("reason", "") for x in analysis.get("verdicts", []) if x.get("risk") == risk), "AI analysis"),
                "action": "none",
            }
            self.db.log_event("ssh_ai_check", ip, decision["reason"], risk, confidence, attempts)
            if self.enabled and risk in {"high", "critical"} and confidence >= self.confidence and bool(analysis.get("consensus")):
                ok, message = confirm_block(ip, actor="xfi-guard-auto", reason="AI confirmed SSH brute-force", metadata=decision)
                decision["action"] = "blocked" if ok else "block_failed"
                decision["message"] = message
                self.db.log_event("auto_block", ip, message, risk, confidence, attempts)
            results.append(decision)
        return results
