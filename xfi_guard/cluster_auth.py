"""Cluster node identity and signed heartbeat helpers."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time


_NONCE_LOCK = threading.Lock()
_SEEN_NONCES: dict[str, float] = {}
_MAX_NONCES = 4096


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sign_heartbeat(payload: dict, secret: str) -> str:
    return hmac.new(secret.encode(), canonical(payload), hashlib.sha256).hexdigest()


def verify_heartbeat(payload: dict, signature: str, secret: str, max_age: int = 120) -> bool:
    """Verify a fresh HMAC heartbeat and reject nonce replays."""
    try:
        ts = float(payload.get("timestamp", 0))
    except (TypeError, ValueError):
        return False
    try:
        nonce = str(payload.get("nonce", "")).strip()
    except Exception:
        return False
    if not nonce or len(nonce) > 128:
        return False
    now = time.time()
    if abs(now - ts) > max_age:
        return False

    expected = sign_heartbeat(payload, secret)
    if not hmac.compare_digest(expected, str(signature)):
        return False

    with _NONCE_LOCK:
        cutoff = now - max_age
        stale = [key for key, seen_at in _SEEN_NONCES.items() if seen_at < cutoff]
        for key in stale:
            _SEEN_NONCES.pop(key, None)
        # Bind the replay key to the authenticated secret and node identity.
        node_id = str(payload.get("node_id", "")).strip()
        replay_key = f"{hashlib.sha256(secret.encode()).hexdigest()[:16]}:{node_id}:{nonce}"
        if replay_key in _SEEN_NONCES:
            return False
        if len(_SEEN_NONCES) >= _MAX_NONCES:
            oldest = min(_SEEN_NONCES, key=_SEEN_NONCES.get)
            _SEEN_NONCES.pop(oldest, None)
        _SEEN_NONCES[replay_key] = now
    return True


def new_node_id() -> str:
    return "node_" + secrets.token_hex(12)
