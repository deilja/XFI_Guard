from xfi_guard import security


def test_ufw_active(monkeypatch):
    monkeypatch.setattr(security, "_run", lambda command: (0, "Status: active\n", ""))
    result = security.check_ufw()
    assert result.status == "ok"


def test_ufw_inactive(monkeypatch):
    monkeypatch.setattr(security, "_run", lambda command: (0, "Status: inactive\n", ""))
    result = security.check_ufw()
    assert result.status == "critical"


def test_fail2ban_pong(monkeypatch):
    monkeypatch.setattr(security, "_run", lambda command: (0, "Server replied: pong", ""))
    result = security.check_fail2ban()
    assert result.status == "ok"


def test_ssh_service_active(monkeypatch):
    monkeypatch.setattr(security, "_run", lambda command: (0, "active", ""))
    result = security.check_ssh_service()
    assert result.status == "ok"
