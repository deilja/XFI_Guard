"""AI provider health metrics and adaptive weights for XFI Guard."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .ai import AIAnalyzer, PROVIDERS
from .ai_store import load, save

STATE = Path(os.getenv("XFI_GUARD_AI_HEALTH", "/var/lib/xfi-guard/ai_health.json"))


def _read():
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"providers": {}}
    except (OSError, ValueError):
        return {"providers": {}}


def _write(data):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        STATE.chmod(0o600)
    except OSError:
        pass


def record(provider, model, ok, latency_ms, error_text=""):
    data = _read()
    key = f"{provider}:{model or '-'}"
    item = data.setdefault("providers", {}).setdefault(key, {"checks": 0, "success": 0, "latency_ms": 0, "errors": 0})
    item["checks"] += 1
    item["success"] += int(bool(ok))
    item["errors"] += int(not ok)
    item["latency_ms"] = round(((item["latency_ms"] * (item["checks"] - 1)) + latency_ms) / item["checks"], 1)
    item["success_rate"] = round(item["success"] / item["checks"], 4)
    item["last_error"] = (error_text or "")[:500]
    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write(data)


def snapshot():
    return _read().get("providers", {})


def adapt_weights(min_weight=0.25, max_weight=1.5):
    cfg = load()
    current = {p: 1.0 for p in PROVIDERS}
    current.update(cfg.get("ai_weights") or {})
    groups = {p: [] for p in PROVIDERS}
    for key, value in snapshot().items():
        provider = key.split(":", 1)[0]
        if provider in groups:
            groups[provider].append(value)
    for provider, items in groups.items():
        if items:
            success = sum(x.get("success_rate", 0) for x in items) / len(items)
            current[provider] = round(max(min_weight, min(max_weight, current.get(provider, 1.0) * (0.5 + success))), 3)
    cfg["ai_weights"] = current
    save(cfg)
    return current


def run_health_check():
    """Run a real check against all configured providers."""
    analyzer = AIAnalyzer()
    models = analyzer.discover_models(force=True)
    analyzer.reset_health()
    checked = analyzer.check_all_providers()
    checked_by_provider = {item.get("provider"): item for item in checked}
    results = []

    for provider in PROVIDERS:
        item = checked_by_provider.get(provider, {})
        candidates = models.get(provider) or []
        model = item.get("model") or (
            analyzer.gemini_model if provider == "gemini" else
            analyzer.groq_model if provider == "groq" else
            analyzer.openrouter_model if provider == "openrouter" else
            analyzer.routerai_model
        ) or (candidates[0] if candidates else "")
        configured = analyzer._has_key(provider)

        if not configured:
            error_text = "API-ключ не настроен"
            ok = False
        elif not model:
            error_text = "модель не обнаружена через API"
            ok = False
        else:
            ok = bool(item.get("ok"))
            error_text = str(item.get("error") or "")
            if not ok and not error_text:
                error_text = "проверка API не прошла"

        latency = float(item.get("latency_ms", 0) or 0)
        record(provider, model, ok, latency, error_text)
        results.append({"provider": provider, "model": model, "ok": ok, "latency_ms": latency, "error": error_text})

    return {"results": results, "weights": adapt_weights(), "timestamp": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    result = run_health_check()
    failed = [x for x in result["results"] if not x["ok"] and x.get("error") != "API-ключ не настроен"]
    print(json.dumps({"ok": not failed, "failed": len(failed), "weights": result["weights"]}, ensure_ascii=False))
