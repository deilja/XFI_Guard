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
    item = data.setdefault("providers", {}).setdefault(
        key, {"checks": 0, "success": 0, "latency_ms": 0, "errors": 0}
    )
    item["checks"] += 1
    item["success"] += int(bool(ok))
    item["errors"] += int(not ok)
    item["latency_ms"] = round(
        ((item["latency_ms"] * (item["checks"] - 1)) + max(0.0, latency_ms))
        / item["checks"],
        1,
    )
    item["success_rate"] = round(item["success"] / item["checks"], 4)
    item["last_error"] = (error_text or "")[:1000]
    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write(data)


def snapshot():
    return _read().get("providers", {})


def adapt_weights(analyzer: AIAnalyzer | None = None, min_weight=0.25, max_weight=1.5):
    """Adapt weights without allowing a currently failed provider to dominate.

    Historical success influences the weight, but live cooldown state wins over
    history. This is important for quota errors such as Gemini HTTP 429: the
    provider stays configured, but its consensus weight is temporarily reduced.
    """
    cfg = load()
    current = {p: 1.0 for p in PROVIDERS}
    current.update(cfg.get("ai_weights") or {})
    groups = {p: [] for p in PROVIDERS}
    for key, value in snapshot().items():
        provider = key.split(":", 1)[0]
        if provider in groups and isinstance(value, dict):
            groups[provider].append(value)

    live = analyzer.health() if analyzer is not None else {}
    for provider in PROVIDERS:
        configured = bool(live.get(provider, {}).get("configured", False)) if live else True
        healthy = bool(live.get(provider, {}).get("healthy", True)) if live else True
        items = groups[provider]
        if not configured:
            current[provider] = 0.0
            continue
        if not healthy:
            current[provider] = min_weight
            continue
        if items:
            success = sum(float(x.get("success_rate", 0.0)) for x in items) / len(items)
            base = float(current.get(provider, 1.0))
            current[provider] = round(
                max(min_weight, min(max_weight, base * (0.5 + success))), 3
            )
        else:
            current[provider] = round(
                max(min_weight, min(max_weight, float(current.get(provider, 1.0)))), 3
            )

    cfg["ai_weights"] = current
    save(cfg)
    return current


def run_health_check():
    """Run a real check against every configured provider."""
    analyzer = AIAnalyzer()
    models = analyzer.discover_models(force=True)
    analyzer.reset_health()

    started = time.monotonic()
    checked = analyzer.check_all_providers()
    total_elapsed_ms = (time.monotonic() - started) * 1000.0
    checked_by_provider = {item.get("provider"): item for item in checked if item.get("provider")}
    results = []

    for provider in PROVIDERS:
        item = checked_by_provider.get(provider) or {}
        candidates = models.get(provider) or []
        if provider == "gemini":
            model = analyzer.gemini_model
        elif provider == "groq":
            model = analyzer.groq_model
        elif provider == "openrouter":
            model = analyzer.openrouter_model
        else:
            model = analyzer.routerai_model
        model = model or (candidates[0] if candidates else "")
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
        results.append(
            {
                "provider": provider,
                "model": model,
                "ok": ok,
                "latency_ms": latency,
                "error": error_text,
                "configured": configured,
            }
        )

    weights = adapt_weights(analyzer)
    return {
        "results": results,
        "weights": weights,
        "elapsed_ms": round(total_elapsed_ms, 1),
        "health": analyzer.health(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    result = run_health_check()
    failed = [
        x for x in result["results"]
        if not x["ok"] and x.get("error") != "API-ключ не настроен"
    ]
    print(
        json.dumps(
            {
                "ok": not failed,
                "failed": len(failed),
                "weights": result["weights"],
                "elapsed_ms": result["elapsed_ms"],
            },
            ensure_ascii=False,
        )
    )
