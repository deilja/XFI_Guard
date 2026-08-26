"""Risk scoring and defense decisions with Fail2Ban timed blocking."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .fail2ban import BAN_SECONDS, ban as fail2ban_ban, banned_ips, jail_active, unban as fail2ban_unban
from .firewall import list_blocked_ips, validate_public_ip

STATE_FILE = Path("/var/lib/xfi-guard/defense.json")
MIN_AI_CONFIDENCE = 0.90
ALLOWED_AI_RISKS = {"critical"}


def _load():
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"history": []}
    except (OSError, ValueError):
        return {"history": []}


def _save(data):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        STATE_FILE.chmod(0o600)
    except OSError:
        pass


def _audit(ip, action, actor, reason, metadata=None):
    state = _load()
    state.setdefault("history", []).append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ip": ip,
        "actor": str(actor),
        "action": action,
        "reason": str(reason)[:500],
        "metadata": metadata or {},
    })
    state["history"] = state["history"][-500:]
    _save(state)


def score_ip(item):
    ip = validate_public_ip(str(item.get("ip", "")))
    events = max(0, int(item.get("events", 0) or 0))
    sources = item.get("sources") or []
    severity = str(item.get("severity", "warning")).lower()
    score = min(100, events * 5 + len(sources) * 15 + (35 if severity == "critical" else 10 if severity == "warning" else 0))
    risk = "critical" if score >= 80 else "high" if score >= 60 else "medium" if score >= 30 else "low"
    return {"ip": ip, "score": score, "risk": risk, "events": events, "sources": list(sources)}


def pending_candidates(items):
    blocked = set(list_blocked_ips()) | set(banned_ips())
    result = []
    for item in items:
        try:
            scored = score_ip(item)
        except ValueError:
            continue
        if scored["ip"] not in blocked:
            result.append(scored)
    return sorted(result, key=lambda x: x["score"], reverse=True)


def _block(ip, actor, reason, metadata=None):
    ip = validate_public_ip(ip)
    if not jail_active():
        message = "Fail2Ban jail 'xfi-guard' недоступен: блокировка отменена."
        _audit(ip, "block_failed", actor, message, metadata)
        return False, message
    ok, message = fail2ban_ban(ip, BAN_SECONDS)
    _audit(ip, "block" if ok else "block_failed", actor, reason, {
        **(metadata or {}),
        "backend": "fail2ban",
        "bantime_seconds": BAN_SECONDS,
        "expires_at": datetime.now(timezone.utc).timestamp() + BAN_SECONDS if ok else None,
    })
    return ok, message


def confirm_block(ip, actor="admin", reason="manual confirmation", metadata=None):
    return _block(ip, actor, reason, metadata)


def ai_block(ip, risk="critical", confidence=1.0, reason="AI automatic defense", metadata=None):
    """Automatically block only an explicitly authorized, high-confidence AI decision.

    The caller must provide a consensus decision record in metadata. A single provider
    verdict, degraded AI state, or unverified request is rejected.
    """
    metadata = dict(metadata or {})
    normalized_risk = str(risk).lower().strip()
    try:
        normalized_confidence = float(confidence)
    except (TypeError, ValueError):
        normalized_confidence = -1.0

    consensus = bool(metadata.get("consensus"))
    providers = metadata.get("providers") or []
    decision_id = str(metadata.get("decision_id") or "").strip()
    degraded = bool(metadata.get("degraded"))
    authorization = str(metadata.get("authorization") or "").strip().lower()

    checks = {
        "risk": normalized_risk in ALLOWED_AI_RISKS,
        "confidence": normalized_confidence >= MIN_AI_CONFIDENCE,
        "consensus": consensus,
        "providers": len(providers) >= 2,
        "decision_id": bool(decision_id),
        "degraded": not degraded,
        "authorization": authorization == "auto_defense",
    }
    if not all(checks.values()):
        _audit(
            validate_public_ip(ip),
            "block_rejected",
            "ai",
            "AI automatic defense authorization failed",
            {**metadata, "checks": checks, "risk": normalized_risk, "confidence": normalized_confidence},
        )
        return False, "Автоматическая блокировка отклонена: AI-решение не прошло проверку авторизации."

    return _block(ip, "ai", reason, {
        **metadata,
        "risk": normalized_risk,
        "confidence": normalized_confidence,
        "automatic": True,
        "authorization": "auto_defense",
    })


def confirm_unblock(ip, actor="admin", reason="manual confirmation", metadata=None):
    ip = validate_public_ip(ip)
    ok, message = fail2ban_unban(ip)
    _audit(ip, "unblock" if ok else "unblock_failed", actor, reason, {**(metadata or {}), "backend": "fail2ban"})
    return ok, message


def reconcile_expired() -> list[dict]:
    """Detect timed Fail2Ban bans that have naturally expired and audit them once."""
    if not jail_active():
        return []
    state = _load()
    history = state.setdefault("history", [])
    active = set(banned_ips())
    already_expired = {str(item.get("ip")) for item in history if item.get("action") == "expired"}
    results: list[dict] = []
    for item in reversed(history):
        if item.get("action") != "block":
            continue
        ip = str(item.get("ip") or "").strip()
        if not ip or ip in active or ip in already_expired:
            continue
        metadata = item.get("metadata") or {}
        expires_at = metadata.get("expires_at")
        if expires_at:
            try:
                if datetime.now(timezone.utc).timestamp() < float(expires_at):
                    continue
            except (TypeError, ValueError):
                pass
        _audit(ip, "expired", "xfi-guard-timer", "Срок автоматической блокировки 7 дней истёк", {"backend": "fail2ban", "bantime_seconds": BAN_SECONDS})
        results.append({"ip": ip, "action": "expired"})
        already_expired.add(ip)
    return results


def history(limit=50):
    return _load().get("history", [])[-max(1, min(limit, 500)):]
