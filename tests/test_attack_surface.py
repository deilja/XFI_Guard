from xfi_guard import attack_surface


def test_attack_surface_merges_sources_and_scores(monkeypatch):
    monkeypatch.setattr(attack_surface, "collect_fail2ban", lambda: [
        {"ip": "8.8.8.8", "source": "fail2ban", "severity": "critical", "reason": "ban", "jail": "sshd"}
    ])
    monkeypatch.setattr(attack_surface, "collect_ufw", lambda: [
        {"ip": "8.8.8.8", "source": "ufw", "severity": "critical", "reason": "deny"}
    ])
    monkeypatch.setattr(attack_surface, "collect_ssh", lambda: [
        {"ip": "8.8.8.8", "source": "ssh", "severity": "warning", "reason": "failed"}
    ] * 3)

    result = attack_surface.collect_attack_surface()
    item = result["ips"][0]
    assert item["ip"] == "8.8.8.8"
    assert set(item["sources"]) == {"fail2ban", "ufw", "ssh"}
    assert item["ssh_failed"] == 3
    assert item["fail2ban_banned"] is True
    assert item["ufw_blocked"] is True
    assert item["risk_score"] == 95
    assert item["risk"] == "КРИТИЧЕСКИЙ"


def test_private_ips_are_not_collected(monkeypatch):
    monkeypatch.setattr(attack_surface, "_run", lambda command: (0, "Jail list: sshd\n", ""))
    assert attack_surface._public_ipv4("192.168.1.10") is None
    assert attack_surface._public_ipv4("10.0.0.1") is None
    assert attack_surface._public_ipv4("8.8.8.8") == "8.8.8.8"
