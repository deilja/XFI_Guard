"""Legacy AI UI compatibility shim.

The Telegram AI interface is now provided by ai_center and ai_model_manager.
This module intentionally registers no handlers to prevent duplicate/legacy menus.
"""
from __future__ import annotations


def install_ai_handlers(dp) -> None:
    """Compatibility no-op; legacy AI handlers are disabled."""
    return None
