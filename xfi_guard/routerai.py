"""RouterAI adapter for XFI Guard.

RouterAI exposes an OpenAI-compatible API. Free models are preferred, while
paid models can be used only when the caller explicitly enables the paid
fallback.
"""
from __future__ import annotations

import json
import os
import time
from urllib import error, request

BASE_URL = "https://routerai.ru/api/v1"


class RouterAIAdapter:
    provider = "routerai"

    def __init__(self, api_key: str | None = None, timeout: float = 20.0):
        self.api_key = api_key or os.getenv("ROUTERAI_API_KEY") or ""
        self.timeout = timeout
        self.last_error = ""
        self._models_cache: list[str] = []
        self._models_cache_ts = 0.0
        self._free_cache: list[str] = []
        self._free_cache_ts = 0.0
        self.cache_ttl = 300.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _request(self, method: str, url: str, payload: dict | None = None) -> dict:
        headers = {
            "Accept": "application/json",
            "User-Agent": "XFI-Guard/1.7",
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

    def models(self, force: bool = False) -> list[str]:
        """Return model IDs visible to the RouterAI account."""
        if not self.configured:
            return []
        if not force and self._models_cache and time.monotonic() - self._models_cache_ts < self.cache_ttl:
            return list(self._models_cache)
        try:
            data = self._request("GET", f"{BASE_URL}/models")
            result = [str(item.get("id")) for item in data.get("data", []) if item.get("id")]
            self._models_cache = list(dict.fromkeys(result))
            self._models_cache_ts = time.monotonic()
            return list(self._models_cache)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return list(self._models_cache)

    def free_models(self, candidates: list[str] | None = None, force: bool = False) -> list[str]:
        """Return only models with an explicitly zero-cost endpoint."""
        if not self.configured:
            return []
        if not force and self._free_cache and time.monotonic() - self._free_cache_ts < self.cache_ttl:
            allowed = set(candidates or self._models_cache or self.models())
            return [m for m in self._free_cache if m in allowed]
        candidates = candidates or self.models(force=force)
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
                    if self._zero(pricing.get("prompt")) and self._zero(pricing.get("completion")) and int(endpoint.get("status", 0) or 0) >= 0:
                        result.append(model)
                        break
            except error.HTTPError as exc:
                self.last_error = f"{model}: HTTP {exc.code}"
            except Exception as exc:
                self.last_error = f"{model}: {type(exc).__name__}: {exc}"
        self._free_cache = list(dict.fromkeys(result))
        self._free_cache_ts = time.monotonic()
        return list(self._free_cache)

    def ordered_models(self, candidates: list[str] | None = None, allow_paid: bool = False) -> list[str]:
        """Return free chat models first, then paid models when explicitly allowed."""
        all_models = list(dict.fromkeys(candidates or self.models()))
        free = self.free_models(all_models)
        if not allow_paid:
            return free
        free_set = set(free)
        paid = [m for m in all_models if m not in free_set]
        return free + paid

    @staticmethod
    def _zero(value) -> bool:
        try:
            return float(value or 0) == 0.0
        except (TypeError, ValueError):
            return False

    def health(self, model: str) -> tuple[bool, str]:
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
        """Analyze with a caller-selected model; paid usage is controlled upstream."""
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
