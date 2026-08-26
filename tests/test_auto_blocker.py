from __future__ import annotations

import sqlite3

from xfi_guard import auto_blocker
from xfi_guard.auto_blocker import AutoBlocker


class FakeAI:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def analyze_consensus(self, event):
        self.calls.append(event)
        return self.result


def _events(ip: str, count: int = 5) -> list[dict]:
    return [{"event_type": "ssh_auth_failed", "ip": ip, "message": f"Failed password from {ip}"} for _ in range(count)]


def _consensus(risk="critical", confidence=0.95, consensus=True, providers_used=2):
    providers = ["gemini", "groq"][:providers_used]
    verdicts = [{"provider": p, "model": "test", "risk": risk, "confidence": confidence, "reason": "SSH brute force"} for p in providers]
    return {
        "verdicts": verdicts,
        "providers_used": providers_used,
        "models_used": len(verdicts),
        "providers": providers,
        "models": ["test"] * len(verdicts),
        "winner": risk,
        "confidence": confidence,
        "consensus": consensus,
        "degraded": providers_used < 2,
    }


def test_below_attempt_threshold_does_not_call_ai(tmp_path):
    blocker = AutoBlocker(enabled=True, min_attempts=5, db_path=str(tmp_path / "security.db"))
    blocker.ai = FakeAI(_consensus())
    assert blocker.evaluate(_events("8.8.8.8", 4)) == []
    assert blocker.ai.calls == []


def test_critical_multi_provider_consensus_blocks_and_authorizes(tmp_path, monkeypatch):
    blocker = AutoBlocker(enabled=True, confidence=0.90, min_attempts=5, db_path=str(tmp_path / "security.db"))
    blocker.ai = FakeAI(_consensus())
    monkeypatch.setattr(auto_blocker, "list_blocked_ips", lambda: [])
    calls = []

    def fake_ai_block(ip, risk, confidence, reason, metadata):
        calls.append((ip, risk, confidence, reason, metadata))
        return True, f"IP {ip} blocked in test"

    monkeypatch.setattr(auto_blocker, "ai_block", fake_ai_block)
    result = blocker.evaluate(_events("8.8.8.8"))

    assert result[0]["action"] == "blocked"
    assert result[0]["providers_used"] == 2
    assert result[0]["decision_id"].startswith("ai-")
    assert calls and calls[0][0] == "8.8.8.8"
    assert calls[0][4]["authorization"] == "auto_defense"
    assert calls[0][4]["consensus"] is True
    assert calls[0][4]["degraded"] is False
    assert calls[0][4]["decision_id"] == result[0]["decision_id"]

    with sqlite3.connect(tmp_path / "security.db") as conn:
        rows = conn.execute("SELECT event_type, ip, risk, confidence, attempts FROM security_events ORDER BY id").fetchall()
    assert rows == [("ssh_ai_check", "8.8.8.8", "SSH brute force", 0.95, 5), ("auto_block", "8.8.8.8", "SSH brute force", 0.95, 5)]


def test_single_provider_never_blocks(tmp_path, monkeypatch):
    blocker = AutoBlocker(enabled=True, confidence=0.90, min_attempts=5, db_path=str(tmp_path / "security.db"))
    blocker.ai = FakeAI(_consensus(providers_used=1))
    monkeypatch.setattr(auto_blocker, "list_blocked_ips", lambda: [])
    monkeypatch.setattr(auto_blocker, "ai_block", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("block must not be called")))
    result = blocker.evaluate(_events("1.1.1.1"))
    assert result[0]["action"] == "none"
    assert result[0]["consensus"] is True
    assert result[0]["degraded"] is True


def test_no_consensus_never_blocks(tmp_path, monkeypatch):
    blocker = AutoBlocker(enabled=True, confidence=0.90, min_attempts=5, db_path=str(tmp_path / "security.db"))
    blocker.ai = FakeAI(_consensus(consensus=False))
    monkeypatch.setattr(auto_blocker, "list_blocked_ips", lambda: [])
    monkeypatch.setattr(auto_blocker, "ai_block", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("block must not be called")))
    result = blocker.evaluate(_events("1.1.1.1"))
    assert result[0]["action"] == "none"


def test_high_risk_never_blocks_automatically(tmp_path, monkeypatch):
    blocker = AutoBlocker(enabled=True, confidence=0.90, min_attempts=5, db_path=str(tmp_path / "security.db"))
    blocker.ai = FakeAI(_consensus(risk="high", confidence=0.99))
    monkeypatch.setattr(auto_blocker, "list_blocked_ips", lambda: [])
    monkeypatch.setattr(auto_blocker, "ai_block", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("high risk must not be auto-blocked")))
    result = blocker.evaluate(_events("9.9.9.9"))
    assert result[0]["action"] == "none"
