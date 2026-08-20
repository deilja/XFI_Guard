"""Explicit approval tokens for XFI Guard remediation workflows.

Approval is intentionally short-lived and bound to the exact plan fingerprint.
Telegram/UI layers should never approve by action name alone.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import asdict
from typing import Any

from .safety.change_guard import ChangePlan

_DEFAULT_TTL = 300


def _secret() -> bytes:
    value = os.getenv("XFI_GUARD_APPROVAL_SECRET", "")
    if not value:
        raise RuntimeError("XFI_GUARD_APPROVAL_SECRET is not configured")
    return value.encode("utf-8")


def plan_fingerprint(plan: ChangePlan) -> str:
    raw = repr(asdict(plan)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def issue_approval(plan: ChangePlan, *, admin_id: int, ttl: int = _DEFAULT_TTL) -> str:
    if admin_id <= 0:
        raise ValueError("invalid admin id")
    if ttl < 30 or ttl > 3600:
        raise ValueError("approval ttl must be between 30 and 3600 seconds")
    expires = int(time.time()) + ttl
    payload = f"{admin_id}:{expires}:{plan_fingerprint(plan)}"
    signature = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}:{signature}"


def verify_approval(plan: ChangePlan, token: str, *, admin_id: int) -> bool:
    try:
        owner, expires, fingerprint, signature = token.split(":", 3)
        if int(owner) != admin_id or int(expires) < int(time.time()):
            return False
        if not hmac.compare_digest(fingerprint, plan_fingerprint(plan)):
            return False
        payload = f"{owner}:{expires}:{fingerprint}"
        expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(signature, expected)
    except (ValueError, TypeError):
        return False


def approval_record(plan: ChangePlan, *, admin_id: int, ttl: int = _DEFAULT_TTL) -> dict[str, Any]:
    token = issue_approval(plan, admin_id=admin_id, ttl=ttl)
    return {
        "plan_id": plan_fingerprint(plan),
        "admin_id": admin_id,
        "token": token,
        "expires_at": int(time.time()) + ttl,
    }
