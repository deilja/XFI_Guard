from datetime import datetime, timezone

from xfi_guard.events import SecurityEvent
from xfi_guard.security_center import summarize


def test_security_summary():
    now = datetime.now(timezone.utc).isoformat()
    events = [
        SecurityEvent(now, "ssh", "ssh_auth_failed", "warning", "bad", "192.0.2.1", "root", "a"),
        SecurityEvent(now, "fail2ban", "ip_banned", "critical", "ban", "192.0.2.1", None, "b"),
    ]
    result = summarize(events)
    assert result["events"] == 2
    assert result["unique_ips"] == 1
    assert result["critical"] == 1
