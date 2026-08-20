from types import SimpleNamespace

from xfi_guard.remediation_telegram import remediation_keyboard, remediation_text, result_text


def test_remediation_text_contains_plan_data():
    plan = SimpleNamespace(action="restart", target="x-ui", risk="high", reason="health check failed")
    text = remediation_text(plan)
    assert "restart" in text
    assert "x-ui" in text
    assert "health check failed" in text
    assert "Подтверждения" in text or "подтверждения" in text


def test_keyboard_binds_plan_id():
    keyboard = remediation_keyboard("abc123")
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "xfi:rem:approve:abc123" in callbacks
    assert "xfi:rem:reject:abc123" in callbacks
    assert "xfi:rem:detail:abc123" in callbacks
    assert "xfi:rem:cancel:abc123" in callbacks


def test_result_text():
    text = result_text("verified", "abc123", "OK")
    assert "Изменение проверено" in text
    assert "abc123" in text
    assert "OK" in text
