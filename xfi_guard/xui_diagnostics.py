"""Read-only 3X-UI diagnostics for the Telegram administration bot.

The module deliberately performs no configuration changes. It checks API reachability,
authentication, inbound inventory, common configuration mistakes, listening ports,
and local 3X-UI/Xray service health when available.
"""
from __future__ import annotations

import asyncio
import socket
import subprocess
import time
from urllib.parse import urlparse

from .xui_inbounds import XUIClient


def _service_status(name: str) -> dict:
    try:
        p = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        state = (p.stdout or "").strip() or "unknown"
        return {"service": name, "state": state, "active": state == "active"}
    except Exception as exc:
        return {"service": name, "state": "error", "active": False, "error": type(exc).__name__}


def _candidate_services() -> list[dict]:
    result = []
    seen = set()
    for name in ("x-ui", "3x-ui", "xray", "xray.service"):
        if name in seen:
            continue
        seen.add(name)
        result.append(_service_status(name))
    return result


def _port_check(host: str, port: int, timeout: float = 2.5) -> dict:
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return {"ok": True, "latency_ms": round((time.monotonic() - started) * 1000, 1)}
    except OSError as exc:
        return {
            "ok": False,
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _inspect_inbounds(items: list[dict]) -> dict:
    findings = []
    ports: dict[int, list[str]] = {}
    enabled = 0
    protocols: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            findings.append("inbound: некорректный объект")
            continue
        remark = str(item.get("remark") or item.get("tag") or item.get("id") or "?")
        port = _parse_int(item.get("port"))
        protocol = str(item.get("protocol") or "unknown").lower()
        protocols[protocol] = protocols.get(protocol, 0) + 1
        if item.get("enable") is not False:
            enabled += 1
        if port is None or not 1 <= port <= 65535:
            findings.append(f"{remark}: некорректный порт {item.get('port')!r}")
        else:
            ports.setdefault(port, []).append(remark)
        for field in ("settings", "streamSettings", "sniffing"):
            if field not in item:
                findings.append(f"{remark}: отсутствует {field}")
            elif not isinstance(item[field], dict):
                findings.append(f"{remark}: {field} не является объектом")
    for port, names in ports.items():
        if len(names) > 1:
            findings.append(f"порт {port}: несколько inbound ({', '.join(names[:4])})")
    return {
        "total": len(items),
        "enabled": enabled,
        "disabled": max(0, len(items) - enabled),
        "protocols": protocols,
        "findings": findings,
        "ports": sorted(ports),
    }


def diagnose_profile(item: dict) -> dict:
    """Run a read-only diagnostic for one stored 3X-UI profile."""
    started = time.monotonic()
    result = {
        "name": item.get("name", "unknown"),
        "url": item.get("url", ""),
        "api": {"ok": False},
        "inbounds": {},
        "port_checks": [],
        "services": _candidate_services(),
        "findings": [],
    }
    client = XUIClient(item["url"], item.get("token") or None, timeout=8)
    try:
        status, body = client.list_inbounds()
        result["api"] = {
            "ok": status < 300 and bool(body.get("success", True)),
            "http_status": status,
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "message": body.get("msg", ""),
        }
        if not result["api"]["ok"]:
            result["findings"].append("API недоступен или авторизация отклонена")
            return result
        items = body.get("obj") or []
        result["inbounds"] = _inspect_inbounds(items)
        result["findings"].extend(result["inbounds"]["findings"])
        parsed = urlparse(item["url"])
        host = parsed.hostname
        if host:
            for port in result["inbounds"].get("ports", [])[:30]:
                check = _port_check(host, port)
                result["port_checks"].append({"port": port, **check})
                if not check["ok"]:
                    result["findings"].append(f"порт {port}: TCP недоступен с сервера XFI Guard")
    except Exception as exc:
        result["api"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        result["findings"].append(f"Ошибка запроса API: {type(exc).__name__}")
    return result


def diagnose_all(items: list[dict]) -> list[dict]:
    return [diagnose_profile(item) for item in items]


def format_diagnostics(report: list[dict]) -> str:
    """Produce a Telegram-safe compact report without exposing API tokens."""
    if not report:
        return "🔍 Полная диагностика 3X-UI\n\n❌ Нет сохранённых подключений."
    lines = ["🔍 ПОЛНАЯ ДИАГНОСТИКА 3X-UI", ""]
    for item in report:
        api = item["api"]
        ib = item.get("inbounds") or {}
        lines.append(f"⚙️ {item['name']}")
        if api.get("ok"):
            lines.append(f"🟢 API: OK ({api.get('http_status', '-')}, {api.get('latency_ms', '-')} ms)")
            lines.append(f"📡 Inbounds: {ib.get('total', 0)} | активных: {ib.get('enabled', 0)} | выключенных: {ib.get('disabled', 0)}")
            protocols = ", ".join(f"{k}:{v}" for k, v in sorted((ib.get("protocols") or {}).items())) or "нет"
            lines.append(f"🔌 Протоколы: {protocols}")
            ports = item.get("port_checks") or []
            if ports:
                ok = sum(1 for x in ports if x.get("ok"))
                lines.append(f"🌐 TCP портов проверено: {len(ports)}, доступно: {ok}")
        else:
            lines.append(f"🔴 API: ERROR — {api.get('error') or api.get('message') or 'недоступен'}")
        active = [x["service"] for x in item.get("services", []) if x.get("active")]
        lines.append(f"🧩 Активные сервисы: {', '.join(active) if active else 'не обнаружены'}")
        findings = item.get("findings") or []
        if findings:
            lines.append("⚠️ Проблемы:")
            for finding in findings[:8]:
                lines.append(f"• {finding}")
        else:
            lines.append("✅ Явных проблем не обнаружено")
        lines.append("")
    return "\n".join(lines)[:3900]
