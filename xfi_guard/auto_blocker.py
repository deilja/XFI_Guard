"""AI-assisted SSH auto-blocking with automatic seven-day Fail2Ban bans."""
from __future__ import annotations

import ipaddress
import os

from .ai import AIAnalyzer
from .auto_defense import ai_block
from .firewall import list_blocked_ips
from .security_db import SecurityDB


class AutoBlocker:
    def __init__(self, *, enabled=False, confidence=0.90, min_attempts=5, min_providers=1,
                 db_path="/var/lib/xfi-guard/security.db", attempt_window_seconds=600):
        self.enabled = enabled
        self.confidence = max(0.0, min(1.0, float(confidence)))
        self.min_attempts = max(1, int(min_attempts))
        self.min_providers = max(1, int(min_providers))
        self.attempt_window_seconds = max(60, int(attempt_window_seconds))
        self.ai = AIAnalyzer()
        self.db = SecurityDB(db_path)
        self.whitelist = self._load_whitelist()

    @staticmethod
    def _load_whitelist() -> set[str]:
        raw = os.getenv("XFI_GUARD_AUTO_BLOCK_WHITELIST", "")
        result = set()
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

    def evaluate(self, events):
        grouped = {}
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
            normalized = parsed.compressed
            grouped.setdefault(normalized, []).append(event)
            self.db.record_ssh_attempt(normalized)

        blocked = {str(ip).strip() for ip in list_blocked_ips()}
        results = []
        for ip, items in grouped.items():
            attempts = self.db.recent_ssh_attempts(ip, self.attempt_window_seconds)
            if attempts < self.min_attempts or ip in blocked:
                continue
            analysis = next((item.get("ai_consensus") for item in items if item.get("ai_consensus")), None)
            if not analysis:
                analysis = self.ai.analyze_consensus({"event_type": "ssh_bruteforce", "ip": ip,
                                                      "failed_attempts": attempts, "events": items})
            risk = str(analysis.get("winner", "unknown")).lower()
            confidence = float(analysis.get("confidence", 0) or 0)
            providers_used = int(analysis.get("providers_used", 0) or 0)
            decision = {
                "ip": ip, "attempts": attempts, "risk": risk, "confidence": confidence,
                "consensus": bool(analysis.get("consensus")), "providers_used": providers_used,
                "providers": analysis.get("providers", []),
                "analysis_mode": ("full_consensus" if providers_used >= 3 else
                                   "partial_consensus" if providers_used >= 2 else
                                   "fallback" if providers_used == 1 else "unavailable"),
                "reason": next((x.get("reason", "") for x in analysis.get("verdicts", []) if x.get("risk") == risk), "AI analysis"),
                "action": "none",
            }
            self.db.log_event("ssh_ai_check", ip, decision["reason"], risk, confidence, attempts)
            # AI is authoritative for automatic defense: no Telegram/admin confirmation is required.
            # One healthy provider is enough; the confidence threshold remains the safety gate.
            if self.enabled and providers_used >= self.min_providers and risk in {"high", "critical"} and confidence >= self.confidence:
                ok, message = ai_block(ip, risk=risk, confidence=confidence,
                                       reason="AI automatic SSH threat blocking",
                                       metadata=decision)
                decision["action"] = "blocked" if ok else "block_failed"
                decision["message"] = message
                self.db.log_event("auto_block", ip, message, risk, confidence, attempts)
            results.append(decision)
        return results
