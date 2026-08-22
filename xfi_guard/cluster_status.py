"""Cluster status classification for the Telegram Cluster Center."""
from __future__ import annotations

import time

ONLINE_TTL = 90
DEGRADED_TTL = 180


def node_status(node: dict, now: float | None = None) -> tuple[str, str]:
    now = time.time() if now is None else now
    last_seen = float(node.get("last_seen", 0) or 0)
    age = max(0, int(now - last_seen)) if last_seen else 10**9
    if age <= ONLINE_TTL:
        return "online", f"heartbeat {age}s ago"
    if age <= DEGRADED_TTL:
        return "degraded", f"heartbeat {age}s ago"
    return "offline", "heartbeat timeout"


def cluster_summary(nodes: list[dict], now: float | None = None) -> dict:
    now = time.time() if now is None else now
    counts = {"online": 0, "degraded": 0, "offline": 0}
    for node in nodes:
        status, reason = node_status(node, now)
        node["status"] = status
        node["status_reason"] = reason
        counts[status] += 1
    if counts["offline"]:
        overall = "offline" if counts["online"] == 0 else "degraded"
    elif counts["degraded"]:
        overall = "degraded"
    else:
        overall = "online"
    return {"status": overall, "counts": counts, "total": len(nodes)}
