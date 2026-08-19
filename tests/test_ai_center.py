from xfi_guard.ai_center import ai_center_menu, build_health_report, consensus_report


def _labels(markup):
    return [button.text for row in markup.keyboard for button in row]


def test_ai_center_menu_contains_health_and_sync_controls():
    labels = _labels(ai_center_menu())
    assert "🩺 Здоровье AI" in labels
    assert "🔄 Синхронизация AI" in labels
    assert "📊 Консенсус AI" in labels
    assert "🧹 Сброс здоровья AI" in labels


def test_health_report_handles_empty_provider_set():
    text = build_health_report({"results": [], "weights": {}})
    assert "Нет доступных AI-провайдеров" in text


def test_consensus_report_is_deterministic():
    text = consensus_report({
        "selected_provider": "openrouter",
        "available_providers": ["gemini", "openrouter"],
        "min_consensus": 0.60,
        "ai_weights": {"gemini": 1.0, "groq": 0.5, "openrouter": 1.2},
    })
    assert "openrouter" in text
    assert "60%" in text
