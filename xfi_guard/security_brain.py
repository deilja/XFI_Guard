"""XFI Guard Security Brain: deterministic risk + multi-model consensus."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .ai import AIAnalyzer
from .attack_surface import collect_attack_surface

STATE_FILE = Path("/var/lib/xfi-guard/security_brain.json")


def _load() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"history": []}
    except (OSError, ValueError):
        return {"history": []}


def _save(data: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        STATE_FILE.chmod(0o600)
    except OSError:
        pass


def analyze(limit: int = 10) -> dict:
    surface = collect_attack_surface()
    analyzer = AIAnalyzer()
    active = surface.get("ips", [])[:max(1, min(limit, 25))]
    results = []
    for item in active:
        consensus = analyzer.analyze_consensus({
            "ip": item["ip"], "risk_score": item["risk_score"], "risk": item["risk"],
            "events": item["events"], "sources": item["sources"], "reasons": item["reasons"]
        })
        results.append({"ip": item["ip"], "local_score": item["risk_score"], "local_risk": item["risk"], "consensus": consensus})
    state = _load()
    state.setdefault("history", []).append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_count": surface.get("active_count", 0),
        "results": results,
    })
    state["history"] = state["history"][-100:]
    _save(state)
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "surface": surface, "results": results}


def history(limit: int = 20) -> list[dict]:
    return _load().get("history", [])[-max(1, min(limit, 100)):]
