from xfi_guard.events import deduplicate, parse_line


def test_parse_failed_ssh():
    event = parse_line("Failed password for invalid user admin from 192.0.2.10 port 22 ssh2")
    assert event is not None
    assert event.event_type == "ssh_auth_failed"
    assert event.ip == "192.0.2.10"
    assert event.user == "admin"


def test_parse_fail2ban_ban():
    event = parse_line("NOTICE [sshd] Ban 192.0.2.10", source="fail2ban")
    assert event is not None
    assert event.event_type == "ip_banned"
    assert event.severity == "critical"


def test_deduplicate():
    event = parse_line("Failed password for root from 192.0.2.10 port 22 ssh2")
    assert event is not None
    assert len(deduplicate([event, event])) == 1
