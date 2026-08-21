"""Signed, pull-based multi-VPS threat sharing primitives."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from .threat_intel import report, mark_blocked


def sign_event(payload: dict, secret: str) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_event(payload: dict, signature: str, secret: str) -> bool:
    return hmac.compare_digest(sign_event(payload, secret), str(signature))


def accept_event(payload: dict, signature: str, secret: str) -> dict:
    if not verify_event(payload, signature, secret):
        raise ValueError("invalid cluster signature")
    if abs(time.time() - float(payload.get("timestamp", 0))) > 300:
        raise ValueError("stale cluster event")
    return report(payload["ip"], payload.get("node", "unknown"), payload.get("score", 0), payload.get("risk", "low"), payload.get("events", 1), payload.get("source", "cluster"))


def make_event(ip: str, node: str, score: int, risk: str, events: int, source: str, secret: str) -> dict:
    payload = {"ip": ip, "node": node, "score": int(score), "risk": risk, "events": int(events), "source": source, "timestamp": time.time()}
    payload["signature"] = sign_event(payload, secret)
    return payload


def register_global_block(ip: str, node: str, until: float) -> dict:
    return mark_blocked(ip, node, until, "cluster")
