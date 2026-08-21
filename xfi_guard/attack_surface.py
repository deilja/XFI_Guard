"""Consolidated read-only attack inventory for XFI Guard."""
from __future__ import annotations

import ipaddress
import re
from typing import Any

from .checks import _run
from .config import load_config
from .events import parse_file
from .firewall import list_blocked_ips

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_FAILED_PASSWORD_RE = re.compile(r"Failed password for (?:invalid user )?\S+ from ([0-9.]+)")


def _public_ipv4(value: str) -> str | None:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return None
    return ip.compressed if ip.version == 4 and ip.is_global else None


def collect_fail2ban() -> list[dict[str, Any]]:
    code, out, _ = _run(["fail2ban-client", "status"])
    if code != 0:
        return []
    match = re.search(r"Jail list:\s*(.*)", out)
    if not match:
        return []
    result: list[dict[str, Any]] = []
    for jail in (x.strip() for x in match.group(1).split(",")):
        if not jail or not re.fullmatch(r"[A-Za-z0-9_.:-]+", jail):
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
                result.append({"ip": ip, "source": "fail2ban", "event_type": "fail2ban_banned", "severity": "critical", "reason": f"Fail2Ban: заблокирован в jail {jail}", "jail": jail})
    return result


def collect_ufw() -> list[dict[str, Any]]:
    # Correct UFW syntax is `status numbered`; the previous `status number`
    # silently returned no rules on current Ubuntu/UFW releases.
    code, out, _ = _run(["ufw", "status", "numbered"])
    if code != 0:
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in out.splitlines():
        if "DENY" not in line.upper() and "REJECT" not in line.upper():
            continue
        for raw in _IP_RE.findall(line):
            ip = _public_ipv4(raw)
            if ip and ip not in seen:
                seen.add(ip)
                result.append({"ip": ip, "source": "ufw", "event_type": "ufw_blocked", "severity": "critical", "reason": "UFW: адрес находится в deny/reject правилах"})
    return result


def collect_ssh() -> list[dict[str, Any]]:
    """Read SSH failures from the configured log; journal is fallback only."""
    cfg = load_config()
    failures: list[dict[str, Any]] = []
    for event in parse_file(cfg.ssh_log, "ssh"):
        if event.event_type != "ssh_auth_failed" or not event.ip:
            continue
        ip = _public_ipv4(event.ip)
        if ip:
            failures.append({"ip": ip, "source": "ssh", "event_type": event.event_type, "severity": event.severity, "reason": event.message})
    if failures:
        return failures
    for unit in ("ssh", "sshd"):
        code, out, _ = _run(["journalctl", "-u", unit, "--since", "24 hours ago", "--no-pager", "-o", "cat"])
        if code != 0:
            continue
        for line in out.splitlines():
            match = _FAILED_PASSWORD_RE.search(line)
            if match:
                ip = _public_ipv4(match.group(1))
                if ip:
                    failures.append({"ip": ip, "source": "ssh", "event_type": "ssh_auth_failed", "severity": "warning", "reason": line.strip()})
        if failures:
            break
    return failures


def _ufw_blocked() -> set[str]:
    try:
        return {ip for raw in list_blocked_ips() if (ip := _public_ipv4(str(raw).strip()))}
    except Exception:
        return set()


def _risk_for(entry: dict[str, Any]) -> tuple[int, str]:
    count = int(entry["ssh_failed"])
    score = 0
    for threshold, value in ((1, 10), (3, 25), (5, 40), (10, 55), (20, 70), (40, 85), (80, 95)):
        if count >= threshold:
            score = value
    if len(entry["sources"]) >= 2:
        score += 10
    if len(entry["sources"]) >= 3:
        score += 5
    if entry.get("fail2ban_banned"):
        score = max(score, 95)
    elif entry.get("ufw_blocked"):
        score = max(score, 90)
    score = min(score, 100)
    return score, ("КРИТИЧЕСКИЙ" if score >= 85 else "ВЫСОКИЙ" if score >= 60 else "СРЕДНИЙ" if score >= 25 else "НИЗКИЙ")


def collect_attack_surface() -> dict[str, Any]:
    """Build a complete inventory and distinguish active from already blocked threats."""
    sources = {"fail2ban": collect_fail2ban(), "ufw": collect_ufw(), "ssh": collect_ssh()}
    blocked = _ufw_blocked()
    blocked.update(x["ip"] for x in sources["fail2ban"])
    grouped: dict[str, dict[str, Any]] = {}

    for source, items in sources.items():
        for item in items:
            ip = item["ip"]
            entry = grouped.setdefault(ip, {
                "ip": ip, "sources": [], "events": 0, "ssh_failed": 0,
                "fail2ban_banned": False, "ufw_blocked": False,
                "blocked": ip in blocked, "severity": "warning", "reasons": [], "jails": [],
            })
            if source not in entry["sources"]:
                entry["sources"].append(source)
            entry["events"] += 1
            if source == "ssh":
                entry["ssh_failed"] += 1
            if source == "fail2ban":
                entry["fail2ban_banned"] = True
            if source == "ufw":
                entry["ufw_blocked"] = True
            if item.get("jail") and item["jail"] not in entry["jails"]:
                entry["jails"].append(item["jail"])
            if item.get("severity") == "critical":
                entry["severity"] = "critical"
            reason = str(item.get("reason", "")).strip()
            if reason and reason not in entry["reasons"]:
                entry["reasons"].append(reason)

    for entry in grouped.values():
        score, risk = _risk_for(entry)
        entry["risk_score"], entry["risk"] = score, risk
        entry["reason"] = f"SSH: {entry['ssh_failed']} неудачных попыток входа" if entry["ssh_failed"] else "; ".join(entry["reasons"][:3])
        if len(entry["sources"]) > 1 and entry["ssh_failed"]:
            entry["reason"] += f"; источники: {', '.join(entry['sources'])}"

    ips = sorted(grouped.values(), key=lambda x: (-x["risk_score"], -x["events"], x["ip"]))
    active = [x for x in ips if not x["blocked"]]
    blocked_entries = [x for x in ips if x["blocked"]]
    return {
        "generated_from": ["fail2ban", "ufw", "ssh"],
        "blocked_count": len(blocked),
        "active_count": len(active),
        "blocked_critical_count": sum(1 for x in blocked_entries if x["risk_score"] >= 85),
        "active_critical_count": sum(1 for x in active if x["risk_score"] >= 85),
        "fail2ban_count": len({x["ip"] for x in sources["fail2ban"]}),
        "ufw_count": len({x["ip"] for x in sources["ufw"]}),
        "ssh_count": len(sources["ssh"]),
        "ips": ips,
    }
