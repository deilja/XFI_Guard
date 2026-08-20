"""Legacy AI UI compatibility shim.

The Telegram AI interface is now provided by ai_center and ai_model_manager.
This module intentionally registers no handlers to prevent duplicate/legacy menus.
"""
from __future__ import annotations


def install_ai_handlers(dp) -> None:
    """Compatibility no-op; legacy AI handlers are disabled."""
    return None


def _groq_diagnostics(*args, **kwargs) -> dict:
    """Return a small, dependency-free Groq diagnostics payload.

    Kept for compatibility with older diagnostics/tests that imported this
    helper from ``ai_ui``. The active Telegram AI UI does not depend on it.
    """
    return {
        "provider": "groq",
        "configured": False,
        "healthy": False,
        "error": "legacy diagnostics compatibility shim",
    }
