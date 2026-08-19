"""Telegram UI for VPN/Xray health checks."""
from __future__ import annotations

from typing import Iterable

from .vpn import collect_vpn_checks


def _icon(status: str) -> str:
    return {"ok": "🟢", "warning": "🟡", "critical": "🔴", "unknown": "⚪"}.get(status, "⚪")


def format_vpn_status(results: Iterable[object], limit: int = 3800) -> str:
    lines = ["🌐 VPN / Xray", ""]
    for item in results:
        status = str(getattr(item, "status", "unknown"))
        name = str(getattr(item, "name", "check"))
        message = str(getattr(item, "message", "Нет данных"))
        lines.append(f"{_icon(status)} {name}: {message}")
    text = "\n".join(lines)
    return text[:limit]


def build_vpn_status_text(
    include_api: bool = True,
    include_logs: bool = True,
    include_local_log_fallback: bool = True,
) -> str:
    results = collect_vpn_checks(
        include_api=include_api,
        include_logs=include_logs,
        include_local_log_fallback=include_local_log_fallback,
    )
    return format_vpn_status(results)
