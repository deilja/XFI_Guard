"""Centralized Telegram administrator authorization for XFI Guard."""
from __future__ import annotations

import os
from collections.abc import Mapping


def admin_ids() -> frozenset[int]:
    result: set[int] = set()
    for value in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(","):
        value = value.strip()
        if value.isdigit():
            result.add(int(value))
    return frozenset(result)


def is_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id in admin_ids()


def authorized(obj: object) -> bool:
    """Authorize aiogram Message/CallbackQuery-like objects by from_user.id."""
    user = getattr(obj, "from_user", None)
    return is_admin(getattr(user, "id", None))


def authorization_snapshot() -> Mapping[str, object]:
    """Return non-secret diagnostics without exposing administrator IDs."""
    return {"configured": bool(admin_ids()), "count": len(admin_ids())}
