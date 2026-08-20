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
    item = data.setdefault("providers", {}).setdefault(
        f"{provider}:{model}",
        {"checks": 0, "success": 0, "latency_ms": 0, "errors": 0},
    )
    item["checks"] += 1
    item["success"] += int(ok)
    item["errors"] += int(not ok)
    item["latency_ms"] = round(
        ((item["latency_ms"] * (item["checks"] - 1)) + latency_ms) / item["checks"],
        1,
    )
    item["success_rate"] = round(item["success"] / item["checks"], 4)
    item["last_error"] = (error_text or "")[:300]
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
            current[provider] = round(
                max(min_weight, min(max_weight, current.get(provider, 1.0) * (0.5 + success))),
                3,
            )
    cfg["ai_weights"] = current
    save(cfg)
    return current


def _configured(analyzer, provider):
    """Resolve provider configuration without requiring private analyzer APIs."""
    try:
        available = analyzer.available_providers()
        return provider in available
    except (AttributeError, TypeError):
        pass

    if provider == "gemini":
        gemini = getattr(analyzer, "gemini", None)
        enabled = getattr(gemini, "enabled", None)
        return bool(enabled() if callable(enabled) else getattr(analyzer, "gemini_key", ""))
    if provider == "groq":
        return bool(getattr(analyzer, "groq_key", ""))
    if provider == "openrouter":
        return bool(getattr(analyzer, "openrouter_key", ""))
    if provider == "routerai":
        return bool(getattr(analyzer, "routerai_key", "")) and bool(
            getattr(analyzer, "routerai_enabled", False)
        )
    return False


def run_health_check():
    analyzer = AIAnalyzer()
    results = []
    models = {
        "gemini": getattr(getattr(analyzer, "gemini", None), "model", ""),
        "groq": getattr(analyzer, "groq_model", ""),
        "openrouter": getattr(
            analyzer,
            "openrouter_model",
            getattr(analyzer, "openrouter_models", [""])[0]
            if getattr(analyzer, "openrouter_models", None)
            else "",
        ),
        "routerai": getattr(analyzer, "routerai_model", ""),
    }

    for provider in PROVIDERS:
        model = models[provider]
        if not _configured(analyzer, provider):
            results.append({
                "provider": provider,
                "model": model,
                "ok": False,
                "latency_ms": 0,
                "error": "API-ключ не настроен",
            })
            continue

        started = time.monotonic()
        ok = False
        err = ""
        try:
            if hasattr(analyzer, "check_provider"):
                checked = analyzer.check_provider(provider, force=True)
                ok = bool(checked.get("ok"))
                err = checked.get("error", "")
            elif hasattr(analyzer, "_chat_model"):
                checked = analyzer._chat_model(
                    provider, model, "Ответь OK", json_mode=True, force=True
                )
                ok = bool(checked)
                err = getattr(analyzer, "last_error", "") if not ok else ""
            else:
                checked = analyzer._call(
                    provider,
                    model,
                    'Ответь только JSON: {"risk":"low","confidence":1,"reason":"health check"}',
                ) if model else None
                ok = bool(checked)
                err = getattr(analyzer, "last_error", "") if not ok else ""
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"

        latency = round((time.monotonic() - started) * 1000, 1)
        record(provider, model, ok, latency, err)
        results.append({
            "provider": provider,
            "model": model,
            "ok": ok,
            "latency_ms": latency,
            "error": err,
        })

    return {
        "results": results,
        "weights": adapt_weights(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    result = run_health_check()
    failed = [
        x for x in result["results"]
        if not x["ok"] and x.get("error") != "API-ключ не настроен"
    ]
    print(json.dumps({
        "ok": not failed,
        "failed": len(failed),
        "weights": result["weights"],
    }, ensure_ascii=False))
