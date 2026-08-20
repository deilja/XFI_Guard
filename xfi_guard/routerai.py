"""RouterAI adapter for XFI Guard.

RouterAI exposes an OpenAI-compatible API.  This adapter is intentionally
standalone so the main AI engine can opt into it without making paid requests
implicitly.  A model is considered eligible only when its endpoint pricing is
explicitly zero for prompt and completion.
"""
from __future__ import annotations

import json
import os
from urllib import error, request

BASE_URL = "https://routerai.ru/api/v1"


class RouterAIAdapter:
    provider = "routerai"

    def __init__(self, api_key: str | None = None, timeout: float = 20.0):
        self.api_key = api_key or os.getenv("ROUTERAI_API_KEY") or ""
        self.timeout = timeout
        self.last_error = ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _request(self, method: str, url: str, payload: dict | None = None) -> dict:
        headers = {
            "Accept": "application/json",
            "User-Agent": "XFI-Guard/1.6",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=data, headers=headers, method=method)
        with request.urlopen(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def models(self) -> list[str]:
        """Return RouterAI model IDs visible to the account."""
        if not self.configured:
            return []
        try:
            data = self._request("GET", f"{BASE_URL}/models")
            return [str(item.get("id")) for item in data.get("data", []) if item.get("id")]
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []

    def free_models(self, candidates: list[str] | None = None) -> list[str]:
        """Return only models having an explicitly zero-cost endpoint.

        RouterAI pricing is endpoint-specific, so model availability alone is
        not sufficient to classify a model as free.
        """
        if not self.configured:
            return []
        candidates = candidates or self.models()
        result: list[str] = []
        for model in candidates:
            if "/" not in model:
                continue
            author, slug = model.split("/", 1)
            try:
                data = self._request("GET", f"{BASE_URL}/models/{author}/{slug}/endpoints")
                endpoints = ((data.get("data") or {}).get("endpoints") or [])
                for endpoint in endpoints:
                    pricing = endpoint.get("pricing") or {}
                    prompt = pricing.get("prompt")
                    completion = pricing.get("completion")
                    if self._zero(prompt) and self._zero(completion) and int(endpoint.get("status", 0) or 0) >= 0:
                        result.append(model)
                        break
            except error.HTTPError as exc:
                self.last_error = f"{model}: HTTP {exc.code}"
            except Exception as exc:
                self.last_error = f"{model}: {type(exc).__name__}: {exc}"
        return list(dict.fromkeys(result))

    @staticmethod
    def _zero(value) -> bool:
        try:
            return float(value or 0) == 0.0
        except (TypeError, ValueError):
            return False

    def health(self, model: str) -> tuple[bool, str]:
        """Probe a model with zero output tokens.

        This is opt-in only; the caller must first establish that the model's
        endpoint pricing is zero if it wants to keep the global free-only rule.
        """
        if not self.configured:
            return False, "API key not configured"
        try:
            result = self._request(
                "POST",
                f"{BASE_URL}/chat/completions",
                {
                    "model": model,
                    "messages": [{"role": "user", "content": "Ответь OK"}],
                    "max_tokens": 1,
                    "temperature": 0,
                    "provider": {"allow_fallbacks": False},
                },
            )
            content = ((result.get("choices") or [{}])[0].get("message") or {}).get("content")
            return bool(content), "" if content else "empty response"
        except error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:600]
            except Exception:
                detail = ""
            return False, f"HTTP {exc.code}: {detail}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def analyze(self, model: str, prompt: str) -> str | None:
        """Analyze using a caller-approved free model only."""
        if not self.configured:
            self.last_error = "API key not configured"
            return None
        try:
            result = self._request(
                "POST",
                f"{BASE_URL}/chat/completions",
                {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Ты аналитик безопасности VPS. Отвечай по-русски."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0,
                    "max_tokens": 500,
                    "provider": {"allow_fallbacks": False},
                },
            )
            content = ((result.get("choices") or [{}])[0].get("message") or {}).get("content")
            if not content:
                self.last_error = "empty response"
                return None
            return str(content)
        except error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:800]
            except Exception:
                detail = ""
            self.last_error = f"HTTP {exc.code}: {detail}"
            return None
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None
