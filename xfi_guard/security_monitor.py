"""Periodic autonomous threat monitor. Detection/AI are advisory; blocking stays manual."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .attack_surface import collect_attack_surface
from .ai import AIAnalyzer

STATE_FILE = Path(os.getenv("XFI_GUARD_MONITOR_STATE", "/var/lib/xfi-guard/security_monitor.json"))


def _load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"seen": {}, "alerts": []}


def _save(data: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        STATE_FILE.chmod(0o600)
    except OSError:
        pass


def scan_once(threshold: int = 60, max_ips: int = 5) -> dict:
    """Scan once and analyze only newly elevated threats."""
    state = _load()
    surface = collect_attack_surface()
    previous = state.setdefault("seen", {})
    candidates = []
    for item in surface.get("ips", []):
        ip = str(item.get("ip", ""))
        score = int(item.get("risk_score", 0) or 0)
        old = int(previous.get(ip, -1))
        previous[ip] = score
        if score >= threshold and (old < threshold or score > old + 10):
            candidates.append(item)
    candidates = sorted(candidates, key=lambda x: int(x.get("risk_score", 0)), reverse=True)[:max(1, min(max_ips, 20))]
    alerts = []
    analyzer = AIAnalyzer()
    for item in candidates:
        consensus = analyzer.analyze_consensus({
            "ip": item.get("ip"), "risk_score": item.get("risk_score"), "risk": item.get("risk"),
            "events": item.get("events"), "sources": item.get("sources"), "reasons": item.get("reasons")
        })
        alert = {"timestamp": datetime.now(timezone.utc).isoformat(), "ip": item.get("ip"), "score": item.get("risk_score"), "risk": item.get("risk"), "consensus": consensus}
        alerts.append(alert)
    state["alerts"] = (state.get("alerts", []) + alerts)[-200:]
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save(state)
    return {"alerts": alerts, "active_count": surface.get("active_count", 0), "scanned": len(surface.get("ips", []))}


def run_forever(interval: int = 300, threshold: int = 60) -> None:
    while True:
        try:
            scan_once(threshold=threshold)
        except Exception as exc:
            data = _load(); data.setdefault("alerts", []).append({"timestamp": datetime.now(timezone.utc).isoformat(), "error": f"{type(exc).__name__}: {exc}"}); data["alerts"] = data["alerts"][-200:]; _save(data)
        time.sleep(max(30, interval))


if __name__ == "__main__":
    run_forever(int(os.getenv("XFI_GUARD_MONITOR_INTERVAL", "300")), int(os.getenv("XFI_GUARD_MONITOR_THRESHOLD", "60")))
