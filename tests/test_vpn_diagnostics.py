"""Regression tests for VPN/Xray diagnostics.

These tests mock system commands and the 3X-UI API boundary so diagnostics can
be checked in CI without requiring Xray, systemd or a live panel.
"""
from xfi_guard import vpn


def test_service_candidates_do_not_warn_when_xui_is_active(monkeypatch):
    def fake_run(args, *_, **__):
        if args[:3] == ["systemctl", "is-active", "x-ui"]:
            return (0, "active", "")
        if args[:3] == ["systemctl", "is-active", "3x-ui"]:
            return (3, "inactive", "")
        if args[:3] == ["systemctl", "is-active", "xray"]:
            return (3, "inactive", "")
        if args[:3] == ["ps", "-eo"]:
            return (0, "123 xray xray run -config /etc/x-ui/xray/config.json", "")
        return (0, "", "")

    monkeypatch.setattr(vpn, "_run", fake_run)
    results = vpn.check_service_candidates()
    three_xui = [r for r in results if r.details.get("service") == "3x-ui"]
    assert three_xui
    assert three_xui[0].status == "info"


def test_api_status_uses_mocked_client():
    class Client:
        base_url = "http://127.0.0.1:2053"

        def get(self, path):
            assert path == "/panel/api/server/status"
            return {"success": True, "obj": {"cpu": 1, "mem": {}, "xray": {"state": "running", "version": "26.7.11"}}}

    result = vpn.check_api_server_status(Client())
    assert result.status == "ok"
    assert "Xray running" in result.message


def test_api_status_detects_stopped_xray():
    class Client:
        base_url = "http://127.0.0.1:2053"

        def get(self, path):
            return {"success": True, "obj": {"xray": {"state": "stopped", "errorMsg": "core stopped"}}}

    result = vpn.check_api_server_status(Client())
    assert result.status == "critical"
    assert "stopped" in result.message


def test_local_log_fallback_finds_existing_log(monkeypatch, tmp_path):
    log = tmp_path / "xray.log"
    log.write_text("INFO xray started\nINFO connection accepted\n", encoding="utf-8")
    monkeypatch.setattr(vpn, "_run", lambda args, **kwargs: (0, log.read_text(encoding="utf-8"), ""))

    result = vpn.check_local_xray_logs((str(log),))
    assert result.status == "ok"
    assert str(log) in result.message


def test_local_log_fallback_reports_missing_log(tmp_path):
    result = vpn.check_local_xray_logs((str(tmp_path / "missing.log"),))
    assert result.status == "info"
    assert "не найден" in result.message


def test_api_checks_share_single_client(monkeypatch):
    class Client:
        base_url = "http://127.0.0.1:2053"

        def get(self, path):
            if path.endswith("server/status"):
                return {"success": True, "obj": {"xray": {"state": "running"}}}
            if path.endswith("inbounds/list"):
                return {"success": True, "obj": [{"enable": True, "protocol": "vless"}]}
            return {"success": True, "obj": []}

        def post(self, path, json_data=None):
            return {"success": True, "obj": []}

        def post_form(self, path, data=None):
            return {"success": True, "obj": []}

    client = Client()
    monkeypatch.setattr(vpn, "_get_api_client", lambda: client)
    results = vpn.collect_vpn_checks(include_api=True, include_logs=True, include_local_log_fallback=False)
    names = {r.name for r in results}
    assert {"api_server_status", "api_online_clients", "api_inbounds", "api_xray_logs", "api_panel_logs"} <= names


def test_xray_process_is_independent_of_systemd(monkeypatch):
    monkeypatch.setattr(vpn, "_xray_processes", lambda: ["1234 xray xray run -config /etc/x-ui/xray/config.json"])
    assert vpn.check_xray_runtime().status == "ok"
