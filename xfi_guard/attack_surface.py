"""Collect a consolidated, read-only view of current attack indicators.

Sources: Fail2Ban active bans, UFW deny/reject rules, and SSH authentication
failures from the configured SSH log and systemd journal. Already blocked IPs
are removed from the *active* attack inventory so the bot does not keep
showing an address after it has been blocked. Collection itself is read-only.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Any

from .checks import _run
from .config import load_config
from .events import parse_file
from .firewall import list_blocked_ips

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_FAILED_PASSWORD_RE = re.compile(
    r"Failed password for (?:invalid user )?\S+ from ([0-9.]+)"
)


def _public_ipv4(value: str) -> str | None:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return None
    return ip.compressed if ip.version == 4 and ip.is_global else None


def _blocked_set() -> set[str]:
    """Return the current firewall/F2B block list without breaking collection."""
    try:
        return {
            ip.compressed
            for raw in list_blocked_ips()
            for ip in [_public_ipv4(str(raw).strip())]
            if ip
        }
    except Exception:
        return set()


def collect_fail2ban() -> list[dict[str, Any]]:
    code, out, _ = _run(["fail2ban-client", "status"])
    if code != 0:
        return []
    match = re.search(r"Jail list:\s*(.*)", out)
    if not match:
        return []
    jails = [x.strip() for x in match.group(1).split(",") if x.strip()]
    result: list[dict[str, Any]] = []
    for jail in jails:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", jail):
            continue
        code, text, _ = _run(["fail2ban-client", "status", jail])
        if code != 0:
            continue
        banned = re.search(r"Banned IP list:\s*(.*)", text)
        if not banned:
            continue
        for raw in banned.group(1).split():
            ip = _public_ipv4(raw)
            if ip:
                result.append({
                    "ip": ip,
                    "source": "fail2ban",
                    "event_type": "fail2ban_banned",
                    "severity": "critical",
                    "reason": f"Fail2Ban: заблокирован в jail {jail}",
                    "jail": jail,
                })
    return result


def collect_ufw() -> list[dict[str, Any]]:
    code, out, _ = _run(["ufw", "status", "number"])
    if code != 0:
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in out.splitlines():
        upper = line.upper()
        if "DENY" not in upper and "REJECT" not in upper:
            continue
        for raw in _IP_RE.findall(line):
            ip = _public_ipv4(raw)
            if ip and ip not in seen:
                seen.add(ip)
                result.append({
                    "ip": ip,
                    "source": "ufw",
                    "event_type": "ufw_blocked",
                    "severity": "critical",
                    "reason": "UFW: адрес уже находится в deny/reject правилах",
                })
    return result


def collect_ssh() -> list[dict[str, Any]]:
    """Collect SSH failures once, preferring the configured log.

    The previous implementation read both auth.log and journald unconditionally,
    which counted the same SSH failure twice on systems where rsyslog forwards
    sshd messages to journald. Journald is now a fallback only when the configured
    log produced no SSH failures.
    """
    cfg = load_config()
    failures: list[dict[str, Any]] = []

    for event in parse_file(cfg.ssh_log, "ssh"):
        if event.event_type != "ssh_auth_failed" or not event.ip:
            continue
        ip = _public_ipv4(event.ip)
        if ip:
            failures.append({
                "ip": ip,
                "source": "ssh",
                "event_type": event.event_type,
                "severity": event.severity,
                "reason": event.message,
            })

    if failures:
        return failures

    for unit in ("ssh", "sshd"):
        code, out, _ = _run([
            "journalctl", "-u", unit, "--since", "24 hours ago",
            "--no-pager", "-o", "cat",
        ])
        if code != 0:
            continue
        for line in out.splitlines():
            match = _FAILED_PASSWORD_RE.search(line)
            if not match:
                continue
            ip = _public_ipv4(match.group(1))
            if ip:
                failures.append({
                    "ip": ip,
                    "source": "ssh",
                    "event_type": "ssh_auth_failed",
                    "severity": "warning",
                    "reason": line.strip(),
                })
        if failures:
            break

    return failures


def _risk_for(entry: dict[str, Any]) -> tuple[int, str]:
    """Score active attackers using event volume plus source diversity."""
    count = int(entry["ssh_failed"])
    score = 0

    if count >= 1:
        score = 10
    if count >= 3:
        score = 25
    if count >= 5:
        score = 40
    if count >= 10:
        score = 55
    if count >= 20:
        score = 70
    if count >= 40:
        score = 85
    if count >= 80:
        score = 95

    # Multiple independent indicators increase confidence in malicious activity.
    if len(entry["sources"]) >= 2:
        score += 10
    if len(entry["sources"]) >= 3:
        score += 5

    score = min(score, 100)
    risk = (
        "КРИТИЧЕСКИЙ" if score >= 85 else
        "ВЫСОКИЙ" if score >= 60 else
        "СРЕДНИЙ" if score >= 25 else
        "НИЗКИЙ"
    )
    return score, risk


def collect_attack_surface() -> dict[str, Any]:
    """Build a deduplicated active attack inventory for reporting and AI."""
    blocked = _blocked_set()
    sources = {
        "fail2ban": collect_fail2ban(),
        "ufw": collect_ufw(),
        "ssh": collect_ssh(),
    }
    grouped: dict[str, dict[str, Any]] = {}

    for source, items in sources.items():
        for item in items:
            ip = item["ip"]
            if ip in blocked:
                continue
            entry = grouped.setdefault(ip, {
                "ip": ip,
                "sources": [],
                "events": 0,
                "ssh_failed": 0,
                "fail2ban_banned": False,
                "ufw_blocked": False,
                "severity": "warning",
                "reasons": [],
                "jails": [],
            })
            if source not in entry["sources"]:
                entry["sources"].append(source)
            entry["events"] += 1
            if source == "ssh":
                entry["ssh_failed"] += 1
            elif source == "fail2ban":
                entry["fail2ban_banned"] = True
                if item.get("jail") and item["jail"] not in entry["jails"]:
                    entry["jails"].append(item["jail"])
            elif source == "ufw":
                entry["ufw_blocked"] = True
            if item["severity"] == "critical":
                entry["severity"] = "critical"
            reason = str(item.get("reason", "")).strip()
            if reason and reason not in entry["reasons"]:
                entry["reasons"].append(reason)

    for entry in grouped.values():
        score, risk = _risk_for(entry)
        entry["risk_score"] = score
        entry["risk"] = risk
        if entry["ssh_failed"]:
            entry["reason"] = (
                f"SSH: {entry['ssh_failed']} неудачных попыток входа"
            )
            if len(entry["sources"]) > 1:
                entry["reason"] += f"; источники: {', '.join(entry['sources'])}"
        else:
            entry["reason"] = "; ".join(entry["reasons"][:3])

    ips = sorted(
        grouped.values(),
        key=lambda x: (-x["risk_score"], -x["events"], x["ip"]),
    )
    return {
        "generated_from": ["fail2ban", "ufw", "ssh"],
        "blocked_count": len(blocked),
        "fail2ban_count": sum(1 for x in sources["fail2ban"] if x["ip"] not in blocked),
        "ufw_count": sum(1 for x in sources["ufw"] if x["ip"] not in blocked),
        "ssh_count": sum(1 for x in sources["ssh"] if x["ip"] not in blocked),
        "ips": ips,
    }
