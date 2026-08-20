"""RouterAI adapter for XFI Guard.

RouterAI exposes an OpenAI-compatible API. Free models are preferred, while
paid models can be used only as an explicit fallback policy.
"""
from __future__ import annotations

import json
import os
import time
from urllib import error, request

BASE_URL = "https://routerai.ru/api/v1"
_NON_CHAT_MARKERS = (
    "image", "video", "rerank", "embedding", "moderation", "whisper",
    "tts", "speech", "audio", "music", "lyria", "veo", "flux", "seedance",
    "seedream", "kling", "sora", "recraft", "riverflow",
)


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
        headers = {"Accept": "application/json", "User-Agent": "XFI-Guard/1.7"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=data, headers=headers, method=method)
        with request.urlopen(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _is_chat_model(model: str) -> bool:
        value = model.lower()
        return not any(marker in value for marker in _NON_CHAT_MARKERS)

    def models(self, force: bool = False) -> list[str]:
        """Return chat-capable model IDs visible to the RouterAI account."""
        if not self.configured:
            return []
        if not force and self._models_cache and time.monotonic() - self._models_cache_ts < self.cache_ttl:
            return list(self._models_cache)
        try:
            data = self._request("GET", f"{BASE_URL}/models")
            result = [
                str(item.get("id")) for item in data.get("data", [])
                if item.get("id") and self._is_chat_model(str(item.get("id")))
            ]
            self._models_cache = list(dict.fromkeys(result))
            self._models_cache_ts = time.monotonic()
            return list(self._models_cache)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return list(self._models_cache)

    def free_models(self, candidates: list[str] | None = None, force: bool = False) -> list[str]:
        """Return only chat models with an explicitly zero-cost endpoint."""
        if not self.configured:
            return []
        if not force and self._free_cache and time.monotonic() - self._free_cache_ts < self.cache_ttl:
            allowed = set(candidates or self._models_cache or self.models())
            return [m for m in self._free_cache if m in allowed]
        candidates = [m for m in (candidates or self.models(force=force)) if self._is_chat_model(m)]
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

    def ordered_models(self, candidates: list[str] | None = None, allow_paid: bool = True) -> list[str]:
        """Return free chat models first and paid chat models after them."""
        all_models = list(dict.fromkeys(candidates or self.models()))
        all_models = [m for m in all_models if self._is_chat_model(m)]
        free = self.free_models(all_models)
        if not allow_paid:
            return free
        free_set = set(free)
        return free + [m for m in all_models if m not in free_set]

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
                "POST", f"{BASE_URL}/chat/completions",
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
        """Try free RouterAI chat models first, then paid models as fallback."""
        if not self.configured:
            self.last_error = "API key not configured"
            return None

        candidates = self.ordered_models(allow_paid=True)
        if model and model in candidates:
            candidates.remove(model)
            free = set(self.free_models(candidates))
            candidates.insert(0, model) if model in free else candidates.append(model)
        if not candidates:
            candidates = [model] if model else []

        errors: list[str] = []
        for candidate in candidates[:12]:
            try:
                result = self._request(
                    "POST", f"{BASE_URL}/chat/completions",
                    {
                        "model": candidate,
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
                if content:
                    self.last_error = ""
                    return str(content)
                errors.append(f"{candidate}: empty response")
            except error.HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    detail = ""
                errors.append(f"{candidate}: HTTP {exc.code}: {detail}")
            except Exception as exc:
                errors.append(f"{candidate}: {type(exc).__name__}: {exc}")

        self.last_error = "; ".join(errors[-4:]) or "no RouterAI chat models available"
        return None
