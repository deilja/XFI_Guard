"""Security event parsing and deterministic deduplication."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

SSH_FAILED = re.compile(r"Failed password for (?:invalid user )?(?P<user>\S+) from (?P<ip>[0-9a-fA-F:.]+)")
SSH_ACCEPTED = re.compile(r"Accepted \S+ for (?P<user>\S+) from (?P<ip>[0-9a-fA-F:.]+)")
FAIL2BAN_BAN = re.compile(r"Ban (?P<ip>[0-9a-fA-F:.]+)")


@dataclass(frozen=True)
class SecurityEvent:
    timestamp: str
    source: str
    event_type: str
    severity: str
    message: str
    ip: str | None = None
    user: str | None = None
    fingerprint: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _event(source: str, event_type: str, severity: str, message: str, *, ip: str | None = None, user: str | None = None) -> SecurityEvent:
    timestamp = datetime.now(timezone.utc).isoformat()
    raw = f"{source}|{event_type}|{ip}|{user}|{message}"
    fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:24]
    return SecurityEvent(timestamp, source, event_type, severity, message, ip, user, fingerprint)


def parse_line(line: str, source: str = "ssh") -> SecurityEvent | None:
    match = SSH_FAILED.search(line)
    if match:
        return _event(source, "ssh_auth_failed", "warning", line.strip(), ip=match.group("ip"), user=match.group("user"))
    match = SSH_ACCEPTED.search(line)
    if match:
        return _event(source, "ssh_auth_success", "info", line.strip(), ip=match.group("ip"), user=match.group("user"))
    match = FAIL2BAN_BAN.search(line)
    if match:
        return _event("fail2ban", "ip_banned", "critical", line.strip(), ip=match.group("ip"))
    return None


def parse_file(path: str | Path, source: str = "ssh") -> list[SecurityEvent]:
    target = Path(path)
    if not target.is_file():
        return []
    events: list[SecurityEvent] = []
    for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        event = parse_line(line, source)
        if event:
            events.append(event)
    return events


def deduplicate(events: list[SecurityEvent]) -> list[SecurityEvent]:
    seen: set[str] = set()
    unique: list[SecurityEvent] = []
    for event in events:
        if event.fingerprint in seen:
            continue
        seen.add(event.fingerprint)
        unique.append(event)
    return unique
