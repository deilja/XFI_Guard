import time

from xfi_guard import auto_defense
from xfi_guard.auto_defense import score_ip, pending_candidates


def valid_metadata():
    metadata = {
        "consensus": True,
        "providers": ["gemini", "groq"],
        "degraded": False,
        "authorization": "auto_defense",
        "ip": "8.8.8.8",
    }
    digest = auto_defense._decision_digest({**metadata, "risk": "critical", "confidence": 0.99})
    metadata["decision_id"] = f"ai-{int(time.time())}-{digest}-00000000"
    return metadata


def test_score_ip_critical():
    result = score_ip({"ip": "8.8.8.8", "events": 10, "sources": ["ssh", "fail2ban"], "severity": "critical"})
    assert result["risk"] == "critical"
    assert result["score"] == 100


def test_pending_candidates_sorts_by_score(monkeypatch):
    monkeypatch.setattr("xfi_guard.auto_defense.list_blocked_ips", lambda: ["1.1.1.1"])
    result = pending_candidates([
        {"ip": "1.1.1.1", "events": 100, "sources": ["ufw"], "severity": "critical"},
        {"ip": "8.8.8.8", "events": 8, "sources": ["ssh", "fail2ban"], "severity": "critical"},
    ])
    assert [x["ip"] for x in result] == ["8.8.8.8"]


def _disable_audit(monkeypatch):
    monkeypatch.setattr(auto_defense, "_audit", lambda *args, **kwargs: None)


def test_ai_block_rejects_single_provider(monkeypatch):
    _disable_audit(monkeypatch)
    metadata = {**valid_metadata(), "providers": ["gemini"]}
    called = {"value": False}
    monkeypatch.setattr(auto_defense, "_block", lambda *args, **kwargs: called.__setitem__("value", True))
    ok, message = auto_defense.ai_block("8.8.8.8", confidence=0.99, metadata=metadata)
    assert ok is False
    assert "отклонена" in message
    assert called["value"] is False


def test_ai_block_rejects_low_confidence(monkeypatch):
    _disable_audit(monkeypatch)
    called = {"value": False}
    monkeypatch.setattr(auto_defense, "_block", lambda *args, **kwargs: called.__setitem__("value", True))
    ok, _ = auto_defense.ai_block("8.8.8.8", confidence=0.89, metadata=valid_metadata())
    assert ok is False
    assert called["value"] is False


def test_ai_block_rejects_degraded_consensus(monkeypatch):
    _disable_audit(monkeypatch)
    called = {"value": False}
    monkeypatch.setattr(auto_defense, "_block", lambda *args, **kwargs: called.__setitem__("value", True))
    ok, _ = auto_defense.ai_block("8.8.8.8", confidence=0.99, metadata={**valid_metadata(), "degraded": True})
    assert ok is False
    assert called["value"] is False


def test_ai_block_rejects_missing_decision_authorization(monkeypatch):
    _disable_audit(monkeypatch)
    called = {"value": False}
    monkeypatch.setattr(auto_defense, "_block", lambda *args, **kwargs: called.__setitem__("value", True))
    ok, _ = auto_defense.ai_block("8.8.8.8", confidence=0.99, metadata={**valid_metadata(), "authorization": ""})
    assert ok is False
    assert called["value"] is False


def test_ai_block_allows_valid_consensus_and_calls_backend(monkeypatch):
    _disable_audit(monkeypatch)
    captured = {}

    def fake_block(ip, actor, reason, metadata=None):
        captured.update(ip=ip, actor=actor, reason=reason, metadata=metadata)
        return True, "blocked"

    monkeypatch.setattr(auto_defense, "_block", fake_block)
    ok, message = auto_defense.ai_block("8.8.8.8", risk="critical", confidence=0.99, reason="confirmed threat", metadata=valid_metadata())
    assert ok is True
    assert message == "blocked"
    assert captured["ip"] == "8.8.8.8"
    assert captured["actor"] == "ai"
    assert captured["metadata"]["automatic"] is True
    assert captured["metadata"]["authorization"] == "auto_defense"


def test_ai_block_rejects_noncritical_risk(monkeypatch):
    _disable_audit(monkeypatch)
    called = {"value": False}
    monkeypatch.setattr(auto_defense, "_block", lambda *args, **kwargs: called.__setitem__("value", True))
    ok, _ = auto_defense.ai_block("8.8.8.8", risk="high", confidence=0.99, metadata=valid_metadata())
    assert ok is False
    assert called["value"] is False
