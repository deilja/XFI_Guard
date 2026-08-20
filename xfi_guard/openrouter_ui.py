"""Legacy OpenRouter UI compatibility shim.

OpenRouter model management is now handled by ai_model_manager.
This module intentionally registers no handlers to prevent duplicate menus.
"""
from __future__ import annotations


def install_openrouter_handlers(dp) -> None:
    """Compatibility no-op; legacy OpenRouter handlers are disabled."""
    return None
