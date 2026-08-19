from xfi_guard.xui_diagnostics import _inspect_inbounds, format_diagnostics


def test_inspect_inbounds_detects_duplicate_ports_and_missing_fields():
    report = _inspect_inbounds([
        {"remark": "A", "port": 443, "protocol": "vless", "settings": {}, "streamSettings": {}, "sniffing": {}},
        {"remark": "B", "port": 443, "protocol": "vless", "settings": {}, "streamSettings": {}, "sniffing": {}},
        {"remark": "bad", "port": 0, "protocol": "vmess"},
    ])
    assert report["total"] == 3
    assert 443 in report["ports"]
    assert any("несколько inbound" in item for item in report["findings"])
    assert any("некорректный порт" in item for item in report["findings"])
    assert report["enabled"] == 3


def test_format_diagnostics_does_not_expose_token():
    text = format_diagnostics([{
        "name": "Germany",
        "url": "https://panel.example.com",
        "api": {"ok": True, "http_status": 200, "latency_ms": 12.3},
        "inbounds": {"total": 2, "enabled": 2, "disabled": 0, "protocols": {"vless": 2}},
        "port_checks": [{"port": 443, "ok": True}],
        "services": [{"service": "x-ui", "active": True}],
        "findings": [],
        "token": "super-secret-token",
    }])
    assert "Germany" in text
    assert "super-secret-token" not in text
    assert "API: OK" in text


def test_format_diagnostics_handles_api_error():
    text = format_diagnostics([{
        "name": "BadNode",
        "url": "https://panel.example.com",
        "api": {"ok": False, "error": "HTTP 401"},
        "inbounds": {},
        "port_checks": [],
        "services": [],
        "findings": ["API недоступен или авторизация отклонена"],
    }])
    assert "API: ERROR" in text
    assert "HTTP 401" in text
