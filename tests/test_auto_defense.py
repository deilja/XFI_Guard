from xfi_guard.auto_defense import score_ip, pending_candidates


def test_score_ip_critical():
    result = score_ip({"ip": "8.8.8.8", "events": 10, "sources": ["ssh", "fail2ban"], "severity": "critical"})
    assert result["risk"] == "critical"
    assert result["score"] == 100


def test_pending_candidates_sorts_by_score(monkeypatch):
    monkeypatch.setattr("xfi_guard.auto_defense.list_blocked_ips", lambda: ["1.1.1.1"])
    result = pending_candidates([
        {"ip": "1.1.1.1", "events": 100, "sources": ["ufw"], "severity": "critical"},
        {"ip": "8.8.8.8", "events": 8, "sources": ["ssh", "fail2ban"], "severity": "critical"},
    ])
    assert [x["ip"] for x in result] == ["8.8.8.8"]
