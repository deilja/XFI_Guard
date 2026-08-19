"""AI-assisted SSH auto-blocking with conservative safety gates."""
from __future__ import annotations

import ipaddress
import os

from .ai import AIAnalyzer
from .auto_defense import confirm_block
from .firewall import list_blocked_ips
from .security_db import SecurityDB


class AutoBlocker:
    def __init__(
        self,
        *,
        enabled: bool = False,
        confidence: float = 0.90,
        min_attempts: int = 5,
        min_providers: int = 2,
        db_path: str = "/var/lib/xfi-guard/security.db",
    ):
        self.enabled = enabled
        self.confidence = max(0.0, min(1.0, float(confidence)))
        self.min_attempts = max(1, int(min_attempts))
        self.min_providers = max(2, int(min_providers))
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

        blocked = {str(ip).strip() for ip in list_blocked_ips()}
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
            providers_used = int(analysis.get("providers_used", 0) or 0)
            consensus = bool(analysis.get("consensus")) and providers_used >= self.min_providers
            decision = {
                "ip": ip,
                "attempts": attempts,
                "risk": risk,
                "confidence": confidence,
                "consensus": consensus,
                "providers_used": providers_used,
                "providers": analysis.get("providers", []),
                "reason": next(
                    (x.get("reason", "") for x in analysis.get("verdicts", []) if x.get("risk") == risk),
                    "AI analysis",
                ),
                "action": "none",
            }
            self.db.log_event("ssh_ai_check", ip, decision["reason"], risk, confidence, attempts)

            if self.enabled and consensus and risk in {"high", "critical"} and confidence >= self.confidence:
                ok, message = confirm_block(
                    ip,
                    actor="xfi-guard-auto",
                    reason="AI multi-provider consensus confirmed SSH brute-force",
                    metadata=decision,
                )
                decision["action"] = "blocked" if ok else "block_failed"
                decision["message"] = message
                self.db.log_event("auto_block", ip, message, risk, confidence, attempts)
            results.append(decision)
        return results
