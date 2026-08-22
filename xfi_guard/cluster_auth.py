"""Cluster node identity and signed heartbeat helpers."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sign_heartbeat(payload: dict, secret: str) -> str:
    return hmac.new(secret.encode(), canonical(payload), hashlib.sha256).hexdigest()


def verify_heartbeat(payload: dict, signature: str, secret: str, max_age: int = 120) -> bool:
    try:
        ts = float(payload.get("timestamp", 0))
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts) > max_age:
        return False
    expected = sign_heartbeat(payload, secret)
    return hmac.compare_digest(expected, str(signature))


def new_node_id() -> str:
    return "node_" + secrets.token_hex(12)
