from xfi_guard.security_monitor import _normalize_consensus


def test_normalize_consensus_rejects_provider_count_without_verdicts():
    result = _normalize_consensus({"providers_used": 2, "models_used": 0, "providers": ["gemini", "groq"], "consensus": True, "confidence": 0})
    assert result["verdicts"] == []
    assert result["providers_used"] == 0
    assert result["models_used"] == 0
    assert result["consensus"] is False
    assert result["winner"] == "unknown"
    assert result["degraded"] is True


def test_normalize_consensus_counts_only_actual_verdicts():
    result = _normalize_consensus({
        "providers_used": 4,
        "models_used": 4,
        "consensus": True,
        "confidence": 0.9,
        "verdicts": [
            {"provider": "gemini", "model": "gemini-test", "risk": "high", "confidence": 0.9},
            {"provider": "gemini", "model": "gemini-test", "risk": "high", "confidence": 0.8},
            {"provider": "groq", "model": "groq-test", "risk": "high", "confidence": 0.9},
        ],
    })
    assert result["providers_used"] == 2
    assert result["models_used"] == 2
    assert result["providers"] == ["gemini", "groq"]
    assert result["models"] == ["gemini-test", "groq-test"]
