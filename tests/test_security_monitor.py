from xfi_guard import security_monitor


def test_scan_only_alerts_new_or_elevated(monkeypatch, tmp_path):
    monkeypatch.setattr(security_monitor, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(security_monitor, "collect_attack_surface", lambda: {"active_count": 1, "ips": [{"ip": "8.8.8.8", "risk_score": 75, "risk": "high", "events": 10, "sources": ["ssh"], "reasons": ["failed login"]}]})
    class FakeAI:
        def analyze_consensus(self, event):
            return {"providers_used": 2, "consensus": True, "verdicts": []}
    monkeypatch.setattr(security_monitor, "AIAnalyzer", FakeAI)
    first = security_monitor.scan_once()
    second = security_monitor.scan_once()
    assert len(first["alerts"]) == 1
    assert len(second["alerts"]) == 0


def test_run_forever_baselines_without_startup_notification(monkeypatch):
    calls = []

    def fake_scan_once(**kwargs):
        calls.append(kwargs)
        return {"alerts": []}

    class StopLoop(BaseException):
        pass

    monkeypatch.setattr(security_monitor, "scan_once", fake_scan_once)
    monkeypatch.setattr(security_monitor.time, "sleep", lambda _: (_ for _ in ()).throw(StopLoop()))

    try:
        security_monitor.run_forever(interval=300, threshold=60)
    except StopLoop:
        pass

    assert calls[0] == {"threshold": 60, "notify": False}
    assert calls[1] == {"threshold": 60, "notify": True}
