from xfi_guard.auto_blocker import AutoBlocker


def _events(count=5):
    return [
        {"event_type": "ssh_auth_failed", "ip": "8.8.8.8", "message": "Failed password"}
        for _ in range(count)
    ]


def test_auto_block_requires_two_providers(monkeypatch, tmp_path):
    monkeypatch.setattr("xfi_guard.auto_blocker.list_blocked_ips", lambda: [])
    monkeypatch.setattr(
        "xfi_guard.auto_blocker.confirm_block",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not block")),
    )
    blocker = AutoBlocker(enabled=True, confidence=0.85, min_attempts=5, db_path=str(tmp_path / "security.db"))
    blocker.ai.analyze_consensus = lambda event: {
        "winner": "high",
        "confidence": 0.99,
        "consensus": True,
        "providers_used": 1,
        "providers": ["groq"],
        "verdicts": [{"risk": "high", "reason": "brute force"}],
    }
    result = blocker.evaluate(_events())
    assert result[0]["action"] == "none"
    assert result[0]["consensus"] is False


def test_auto_block_allows_two_provider_consensus(monkeypatch, tmp_path):
    monkeypatch.setattr("xfi_guard.auto_blocker.list_blocked_ips", lambda: [])
    monkeypatch.setattr("xfi_guard.auto_blocker.confirm_block", lambda *args, **kwargs: (True, "blocked"))
    blocker = AutoBlocker(enabled=True, confidence=0.85, min_attempts=5, db_path=str(tmp_path / "security.db"))
    blocker.ai.analyze_consensus = lambda event: {
        "winner": "high",
        "confidence": 0.94,
        "consensus": True,
        "providers_used": 2,
        "providers": ["gemini", "groq"],
        "verdicts": [
            {"risk": "high", "reason": "brute force"},
            {"risk": "high", "reason": "repeated SSH failures"},
        ],
    }
    result = blocker.evaluate(_events())
    assert result[0]["action"] == "blocked"
    assert result[0]["providers_used"] == 2
