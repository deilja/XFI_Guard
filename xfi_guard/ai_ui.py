"""AI UI compatibility helpers.

The Telegram AI interface is provided by ai_center and ai_model_manager.
This module intentionally registers no handlers, but keeps the legacy Groq
 diagnostics helper used by existing integrations and regression tests.
"""
from __future__ import annotations

from typing import Any


def _groq_diagnostics(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Return a safe, side-effect-free Groq diagnostics payload.

    Network/provider probing belongs to the AI engine. The legacy UI helper is
    retained only as a compatibility API and therefore never performs a
    network request or exposes credentials.
    """
    return {
        "provider": "groq",
        "ok": False,
        "configured": False,
        "error": "diagnostics moved to AIAnalyzer.check_all_providers()",
    }


def install_ai_handlers(dp) -> None:
    """Compatibility no-op; legacy AI handlers are disabled."""
    return None
