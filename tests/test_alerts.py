from xfi_guard.alerts import AlertManager


def test_info_events_are_not_alerted():
    manager = AlertManager(token="x", chat_id="y")
    assert not manager.should_alert({"severity": "info", "fingerprint": "a"})


def test_warning_is_rate_limited():
    manager = AlertManager(token="x", chat_id="y", cooldown=300)
    event = {"severity": "warning", "fingerprint": "a"}
    assert manager.should_alert(event)
    assert not manager.should_alert(event)
