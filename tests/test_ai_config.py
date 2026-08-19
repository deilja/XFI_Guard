import pytest

from xfi_guard.ai_config import AIConfig


def test_ai_config_accepts_valid_values():
    cfg = AIConfig(ai_timeout=15, ai_max_workers=4, ai_min_consensus=0.85)
    assert cfg.ai_timeout == 15
    assert cfg.ai_max_workers == 4
    assert cfg.ai_min_consensus == 0.85


def test_ai_config_rejects_invalid_provider():
    with pytest.raises(ValueError):
        AIConfig(provider="unknown")


def test_ai_config_rejects_invalid_consensus():
    with pytest.raises(ValueError):
        AIConfig(ai_min_consensus=1.5)
