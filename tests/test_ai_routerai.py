from unittest.mock import patch

from xfi_guard.ai import AIAnalyzer


def _configured_ai(*, allow_paid=False):
    cfg = {
        "provider": "routerai",
        "routerai_key": "test-key",
        "routerai_enabled": True,
        "routerai_allow_paid": allow_paid,
        "routerai_model": "provider/paid-chat",
        "routerai_models": ["provider/free-chat", "provider/paid-chat"],
        "ai_timeout": 5,
    }
    with patch("xfi_guard.ai.load", return_value=cfg):
        return AIAnalyzer()


def test_ai_analyzer_calls_routerai_with_paid_fallback_disabled():
    ai = _configured_ai(allow_paid=False)
    with patch.object(ai, "_models_for", return_value=["provider/free-chat"]), \
         patch.object(ai.routerai, "analyze", return_value='{"risk":"low","confidence":0.9,"reason":"ok"}') as analyze:
        result = ai._call("routerai", "provider/paid-chat", "test prompt")

    assert result is not None
    analyze.assert_called_once_with("provider/paid-chat", "test prompt", allow_paid=False)
    assert ai.last_provider == "routerai"
    assert ai.last_model == "provider/paid-chat"


def test_ai_analyzer_passes_explicit_paid_fallback_policy():
    ai = _configured_ai(allow_paid=True)
    with patch.object(ai.routerai, "analyze", return_value='{"risk":"high","confidence":0.8,"reason":"test"}') as analyze:
        result = ai._call("routerai", "provider/paid-chat", "test prompt")

    assert result is not None
    analyze.assert_called_once_with("provider/paid-chat", "test prompt", allow_paid=True)


def test_ai_analyzer_routerai_failure_enters_cooldown():
    ai = _configured_ai(allow_paid=True)
    with patch.object(ai.routerai, "analyze", return_value=None):
        assert ai._call("routerai", "provider/free-chat", "test prompt") is None

    health = ai.health()["routerai"]
    assert health["configured"] is True
    assert health["healthy"] is False
    assert health["failures"] == 1
    assert "routerai" in ai.last_provider_errors


def test_ai_analyzer_consensus_uses_routerai_verdict():
    ai = _configured_ai(allow_paid=False)
    ai._jobs = lambda: [("routerai", "provider/free-chat")]
    with patch.object(ai, "_call", return_value='{"risk":"critical","confidence":0.95,"reason":"attack"}'):
        result = ai.analyze_consensus({"event_type": "ssh", "message": "failed logins"})

    assert result["winner"] == "critical"
    assert result["providers"] == ["routerai"]
    assert result["models"] == ["provider/free-chat"]
    assert result["providers_used"] == 1
    assert result["consensus"] is True
    assert result["mode"] == "fallback"
