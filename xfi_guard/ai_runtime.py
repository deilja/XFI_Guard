"""Runtime failover instrumentation for AIAnalyzer."""
from __future__ import annotations

import time
from typing import Any

from .ai_events import record


def install(analyzer_cls: type) -> type:
    """Wrap analyze() to audit provider failover without exposing secrets."""
    if getattr(analyzer_cls, "_xfi_runtime_failover_installed", False):
        return analyzer_cls

    original = analyzer_cls.analyze

    def analyze(self: Any, event: dict, allow_fallback: bool = True):
        configured = getattr(self, "provider", "")
        started = time.monotonic()
        result = original(self, event, allow_fallback=allow_fallback)
        selected = getattr(self, "last_provider", "")
        model = getattr(self, "last_model", "")
        error = getattr(self, "last_error", "")

        if result is not None and selected and selected != configured:
            record({
                "event": "ai_failover",
                "from_provider": configured,
                "to_provider": selected,
                "model": model,
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "reason": error or "primary_provider_failed_or_unavailable",
                "success": True,
            })
        elif result is None:
            record({
                "event": "ai_analysis_failed",
                "provider": configured,
                "model": model,
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "reason": error or "all_providers_failed",
                "success": False,
            })
        return result

    analyzer_cls.analyze = analyze
    analyzer_cls._xfi_runtime_failover_installed = True
    return analyzer_cls
