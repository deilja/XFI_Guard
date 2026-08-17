"""Collect a consolidated, read-only view of current attack indicators.

Sources: Fail2Ban active bans, UFW deny/reject rules, and SSH authentication
failures from the configured SSH log and systemd journal. Collection is
read-only; firewall changes remain behind explicit administrator approval.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Any

from .checks import _run
from .config import load_config
from .events import parse_file

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


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
                result.append({"ip": ip, "source": "fail2ban", "event_type": "fail2ban_banned", "severity": "critical", "reason": f"Fail2Ban: заблокирован в jail {jail}", "jail": jail})
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
                result.append({"ip": ip, "source": "ufw", "event_type": "ufw_blocked", "severity": "critical", "reason": "UFW: адрес уже находится в deny/reject правилах"})
    return result


def collect_ssh() -> list[dict[str, Any]]:
    cfg = load_config()
    failures: list[dict[str, Any]] = []
    for event in parse_file(cfg.ssh_log, "ssh"):
        if event.event_type != "ssh_auth_failed" or not event.ip:
            continue
        ip = _public_ipv4(event.ip)
        if ip:
            failures.append({"ip": ip, "source": "ssh", "event_type": event.event_type, "severity": event.severity, "reason": event.message})
    for unit in ("ssh", "sshd"):
        code, out, _ = _run(["journalctl", "-u", unit, "--since", "24 hours ago", "--no-pager", "-o", "cat"])
        if code != 0:
            continue
        for line in out.splitlines():
            match = re.search(r"Failed password for (?:invalid user )?\S+ from ([0-9.]+)", line)
            if not match:
                continue
            ip = _public_ipv4(match.group(1))
            if ip:
                failures.append({"ip": ip, "source": "ssh", "event_type": "ssh_auth_failed", "severity": "warning", "reason": line.strip()})
    return failures


def collect_attack_surface() -> dict[str, Any]:
    """Build a deduplicated attack inventory for reporting and AI analysis."""
    sources = {"fail2ban": collect_fail2ban(), "ufw": collect_ufw(), "ssh": collect_ssh()}
    grouped: dict[str, dict[str, Any]] = {}
    for source, items in sources.items():
        for item in items:
            ip = item["ip"]
            entry = grouped.setdefault(ip, {"ip": ip, "sources": [], "events": 0, "ssh_failed": 0, "fail2ban_banned": False, "ufw_blocked": False, "severity": "warning", "reasons": [], "jails": []})
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
            if item.get("reason") and item["reason"] not in entry["reasons"]:
                entry["reasons"].append(item["reason"])

    for entry in grouped.values():
        score = 0
        if entry["ssh_failed"] >= 3: score += 25
        if entry["ssh_failed"] >= 10: score += 20
        if entry["fail2ban_banned"]: score += 35
        if entry["ufw_blocked"]: score += 20
        if len(entry["sources"]) >= 3: score += 15
        entry["risk_score"] = min(score, 100)
        entry["risk"] = "КРИТИЧЕСКИЙ" if score >= 70 else "ВЫСОКИЙ" if score >= 45 else "СРЕДНИЙ" if score >= 20 else "НИЗКИЙ"
        entry["reason"] = "; ".join(entry["reasons"][:3])

    return {"generated_from": ["fail2ban", "ufw", "ssh"], "fail2ban_count": len(sources["fail2ban"]), "ufw_count": len(sources["ufw"]), "ssh_count": len(sources["ssh"]), "ips": sorted(grouped.values(), key=lambda x: (-x["risk_score"], -x["events"], x["ip"]))}
