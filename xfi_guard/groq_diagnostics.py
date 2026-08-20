"""Groq diagnostics used by the Telegram AI panel and support tooling."""
from __future__ import annotations

import json
import os
from urllib import error, request

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-20b"
FALLBACK_MODELS = ("openai/gpt-oss-20b", "llama-3.1-8b-instant")


def test_groq(api_key: str | None, model: str | None = None, timeout: float = 15.0) -> dict:
    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        return {"ok": False, "error": "GROQ_API_KEY не настроен", "model": model or DEFAULT_MODEL}

    requested = model or DEFAULT_MODEL
    candidates = [requested] + [x for x in FALLBACK_MODELS if x != requested]
    errors: list[str] = []

    for candidate in candidates:
        body = {
            "model": candidate,
            "messages": [{"role": "user", "content": "Ответь одним словом: OK"}],
            "temperature": 0,
            "max_tokens": 8,
        }
        req = request.Request(
            GROQ_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
            if content:
                return {"ok": True, "model": candidate, "response": content.strip(), "fallback": candidate != requested}
            errors.append(f"{candidate}: пустой ответ")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            errors.append(f"{candidate}: HTTP {exc.code} {detail}")
            if exc.code not in (400, 404):
                break
        except Exception as exc:
            errors.append(f"{candidate}: {type(exc).__name__}: {exc}")
            break

    return {"ok": False, "model": requested, "error": "; ".join(errors)}
