"""Risk scoring and human-confirmed defense decisions."""
from __future__ import annotations

import ipaddress
import json
from datetime import datetime, timezone
from pathlib import Path

from .firewall import block_ip, list_blocked_ips, validate_public_ip

STATE_FILE = Path("/var/lib/xfi-guard/defense.json")


def _load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"history": []}


def _save(data: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        STATE_FILE.chmod(0o600)
    except OSError:
        pass


def score_ip(item: dict) -> dict:
    """Calculate a deterministic risk score; AI is advisory only."""
    ip = validate_public_ip(str(item.get("ip", "")))
    events = max(0, int(item.get("events", 0) or 0))
    sources = item.get("sources") or []
    severity = str(item.get("severity", "warning")).lower()
    score = min(100, events * 5 + len(sources) * 15 + (35 if severity == "critical" else 10 if severity == "warning" else 0))
    risk = "critical" if score >= 80 else "high" if score >= 60 else "medium" if score >= 30 else "low"
    return {"ip": ip, "score": score, "risk": risk, "events": events, "sources": list(sources)}


def pending_candidates(items: list[dict]) -> list[dict]:
    blocked = set(list_blocked_ips())
    result = []
    for item in items:
        try:
            scored = score_ip(item)
        except ValueError:
            continue
        if scored["ip"] in blocked:
            continue
        result.append(scored)
    return sorted(result, key=lambda x: x["score"], reverse=True)


def confirm_block(ip: str, actor: str = "admin", reason: str = "manual confirmation") -> tuple[bool, str]:
    ip = validate_public_ip(ip)
    ok, message = block_ip(ip)
    if ok:
        state = _load()
        state.setdefault("history", []).append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ip": ip,
            "actor": str(actor),
            "action": "block",
            "reason": str(reason)[:500],
        })
        state["history"] = state["history"][-500:]
        _save(state)
    return ok, message


def history(limit: int = 50) -> list[dict]:
    return _load().get("history", [])[-max(1, min(limit, 500)):]
