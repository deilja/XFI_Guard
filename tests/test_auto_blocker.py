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
    return [
        {
            "event_type": "ssh_auth_failed",
            "ip": ip,
            "message": f"Failed password from {ip}",
            "timestamp": f"2026-08-19T04:30:{i:02d}Z",
        }
        for i in range(count)
    ]


def _consensus(risk="high", confidence=0.95, consensus=True):
    return {
        "verdicts": [
            {"provider": "gemini", "model": "test", "risk": risk, "confidence": confidence, "reason": "SSH brute force"},
            {"provider": "groq", "model": "test", "risk": risk, "confidence": confidence, "reason": "SSH brute force"},
        ],
        "providers_used": 2,
        "models_used": 2,
        "providers": ["gemini", "groq"],
        "models": ["test", "test"],
        "winner": risk,
        "confidence": confidence,
        "consensus": consensus,
    }


def test_below_attempt_threshold_does_not_call_ai(tmp_path):
    blocker = AutoBlocker(enabled=True, min_attempts=5, db_path=str(tmp_path / "security.db"))
    blocker.ai = FakeAI(_consensus())

    result = blocker.evaluate(_events("8.8.8.8", 4))

    assert result == []
    assert blocker.ai.calls == []


def test_high_consensus_blocks_and_audits(tmp_path, monkeypatch):
    blocker = AutoBlocker(
        enabled=True,
        confidence=0.90,
        min_attempts=5,
        db_path=str(tmp_path / "security.db"),
    )
    blocker.ai = FakeAI(_consensus())
    monkeypatch.setattr(auto_blocker, "list_blocked_ips", lambda: [])
    calls = []

    def fake_confirm(ip, actor, reason, metadata):
        calls.append((ip, actor, reason, metadata))
        return True, f"IP {ip} blocked in test"

    monkeypatch.setattr(auto_blocker, "confirm_block", fake_confirm)

    result = blocker.evaluate(_events("8.8.8.8"))

    assert len(result) == 1
    assert result[0]["action"] == "blocked"
    assert result[0]["risk"] == "high"
    assert result[0]["confidence"] == 0.95
    assert calls and calls[0][0] == "8.8.8.8"

    with sqlite3.connect(tmp_path / "security.db") as conn:
        rows = conn.execute(
            "SELECT event_type, ip, risk, confidence, attempts FROM security_events ORDER BY id"
        ).fetchall()

    assert rows == [
        ("ssh_ai_check", "8.8.8.8", "high", 0.95, 5),
        ("auto_block", "8.8.8.8", "high", 0.95, 5),
    ]


def test_no_consensus_never_blocks(tmp_path, monkeypatch):
    blocker = AutoBlocker(
        enabled=True,
        confidence=0.90,
        min_attempts=5,
        db_path=str(tmp_path / "security.db"),
    )
    blocker.ai = FakeAI(_consensus(consensus=False))
    monkeypatch.setattr(auto_blocker, "list_blocked_ips", lambda: [])
    monkeypatch.setattr(
        auto_blocker,
        "confirm_block",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("block must not be called")),
    )

    result = blocker.evaluate(_events("1.1.1.1"))

    assert result[0]["action"] == "none"
    assert result[0]["consensus"] is False


def test_low_risk_never_blocks_even_with_confidence(tmp_path, monkeypatch):
    blocker = AutoBlocker(
        enabled=True,
        confidence=0.90,
        min_attempts=5,
        db_path=str(tmp_path / "security.db"),
    )
    blocker.ai = FakeAI(_consensus(risk="low", confidence=0.99))
    monkeypatch.setattr(auto_blocker, "list_blocked_ips", lambda: [])
    monkeypatch.setattr(
        auto_blocker,
        "confirm_block",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("low risk must not be blocked")),
    )

    result = blocker.evaluate(_events("9.9.9.9"))

    assert result[0]["action"] == "none"
    assert result[0]["risk"] == "low"
