"""Security regression tests for AI and automatic defense authorization."""

import json
import time

from xfi_guard.ai_store import load, save
from xfi_guard.auto_defense import _decision_digest, _decision_id_valid


def test_routerai_paid_is_disabled_by_default(tmp_path):
    path = tmp_path / "ai.json"
    save({"routerai_key": "test-key"}, str(path))
    settings = load(str(path))
    assert settings["routerai_enabled"] is True
    assert settings["routerai_allow_paid"] is False


def test_routerai_explicit_paid_opt_in_is_preserved(tmp_path):
    path = tmp_path / "ai.json"
    save({"routerai_key": "test-key", "routerai_allow_paid": True}, str(path))
    settings = load(str(path))
    assert settings["routerai_allow_paid"] is True


def test_ai_decision_binding_rejects_tampering():
    metadata = {
        "ip": "8.8.8.8",
        "attempts": 7,
        "winner": "critical",
        "risk": "critical",
        "confidence": 0.97,
        "providers": ["gemini", "groq"],
        "verdicts": [{"risk": "critical", "confidence": 0.98, "reason": "bruteforce"}],
    }
    digest = _decision_digest(metadata)
    decision_id = f"ai-{int(time.time())}-{digest}-deadbeef"
    assert _decision_id_valid(decision_id, metadata) is True
    tampered = dict(metadata, confidence=0.99)
    assert _decision_id_valid(decision_id, tampered) is False


def test_ai_decision_binding_rejects_expired():
    metadata = {
        "ip": "8.8.8.8",
        "attempts": 7,
        "winner": "critical",
        "confidence": 0.97,
        "providers": ["gemini", "groq"],
        "verdicts": [],
    }
    digest = _decision_digest(metadata)
    decision_id = f"ai-{int(time.time()) - 901}-{digest}-deadbeef"
    assert _decision_id_valid(decision_id, metadata) is False
