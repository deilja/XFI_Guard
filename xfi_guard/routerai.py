"""RouterAI adapter for XFI Guard.

RouterAI exposes an OpenAI-compatible API. All models visible to the account
are discoverable; free models are preferred, while paid models remain available
as an explicit fallback without a hardcoded model limit.
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
        # Keep standalone adapter usage consistent with AIAnalyzer: persistent
        # AI settings are the primary source, environment is the fallback.
        if api_key is None:
            try:
                from .ai_store import load
                stored = load().get("routerai_key") or ""
            except Exception:
                stored = ""
            api_key = stored or os.getenv("ROUTERAI_API_KEY") or ""
        self.api_key = str(api_key).strip()
        self.timeout = timeout
        self.last_error = ""
        self.last_model = ""
        self._models_cache: list[str] = []
        self._models_meta_cache: dict[str, dict] = {}
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
            "User-Agent": "XFI-Guard/1.9",
        }
        if self.api_key:
            try:
                self.api_key.encode("ascii")
            except UnicodeEncodeError as exc:
                self.last_error = "API key contains non-ASCII characters; replace it with the original RouterAI key"
                raise RuntimeError(self.last_error) from exc
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            req = request.Request(url, data=data, headers=headers, method=method)
            with request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except UnicodeEncodeError as exc:
            self.last_error = "RouterAI HTTP header contains non-ASCII data; check ROUTERAI_API_KEY"
            raise RuntimeError(self.last_error) from exc

    def models(self, force: bool = False) -> list[str]:
        """Return every model exposed by RouterAI; never truncate the catalogue."""
        if not self.configured:
            self.last_error = "API key not configured"
            return []
        if not force and self._models_cache and time.monotonic() - self._models_cache_ts < self.cache_ttl:
            return list(self._models_cache)
        try:
            data = self._request("GET", f"{BASE_URL}/models")
            items = data.get("data", []) if isinstance(data, dict) else []
            result: list[str] = []
            meta: dict[str, dict] = {}
            for item in items:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                model = str(item["id"])
                result.append(model)
                meta[model] = item
            self._models_cache = list(dict.fromkeys(result))
            self._models_meta_cache = meta
            self._models_cache_ts = time.monotonic()
            self.last_error = ""
            return list(self._models_cache)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return list(self._models_cache)

    @classmethod
    def _endpoint_items(cls, data: dict) -> list[dict]:
        if not isinstance(data, dict):
            return []
        payload = data.get("data")
        if isinstance(payload, dict):
            endpoints = payload.get("endpoints")
            if isinstance(endpoints, list):
                return [x for x in endpoints if isinstance(x, dict)]
            nested = payload.get("data")
            if isinstance(nested, list):
                return [x for x in nested if isinstance(x, dict)]
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        endpoints = data.get("endpoints")
        if isinstance(endpoints, list):
            return [x for x in endpoints if isinstance(x, dict)]
        return []

    @classmethod
    def _zero(cls, value) -> bool:
        if isinstance(value, dict):
            value = value.get("value", value.get("amount", value.get("price")))
        if value is None:
            return True
        if isinstance(value, str):
            normalized = value.strip().lower().replace("₽", "").replace("rub", "")
            if normalized in {"", "0", "0.0", "0.00", "0.000000", "free", "бесплатно"}:
                return True
            value = normalized
        try:
            return float(value) == 0.0
        except (TypeError, ValueError):
            return False

    @classmethod
    def _pricing_is_free(cls, pricing: dict | None) -> bool:
        if not isinstance(pricing, dict):
            return False
        if pricing.get("free") is True or pricing.get("is_free") is True:
            return True
        prompt = pricing.get("prompt", pricing.get("input"))
        completion = pricing.get("completion", pricing.get("output"))
        return cls._zero(prompt) and cls._zero(completion)

    @classmethod
    def _model_is_free(cls, item: dict) -> bool:
        if not isinstance(item, dict):
            return False
        for key in ("free", "is_free", "free_tier"):
            if item.get(key) is True:
                return True
        return cls._pricing_is_free(item.get("pricing"))

    def free_models(self, candidates: list[str] | None = None, force: bool = False) -> list[str]:
        """Discover every currently free model without failing the whole catalogue."""
        if not self.configured:
            self.last_error = "API key not configured"
            return []
        if not force and self._free_cache and time.monotonic() - self._free_cache_ts < self.cache_ttl:
            allowed = set(candidates or self._models_cache or self.models())
            return [m for m in self._free_cache if m in allowed]

        all_models = list(dict.fromkeys(candidates or self.models(force=force)))
        result: list[str] = []
        endpoint_failures = 0
        for model in all_models:
            meta = self._models_meta_cache.get(model) or {}
            if self._model_is_free(meta):
                result.append(model)
                continue
            if "/" not in model:
                continue
            author, slug = model.split("/", 1)
            try:
                data = self._request("GET", f"{BASE_URL}/models/{author}/{slug}/endpoints")
                endpoints = self._endpoint_items(data)
                if any(self._model_is_free(endpoint) or self._pricing_is_free(endpoint.get("pricing")) for endpoint in endpoints):
                    result.append(model)
            except Exception as exc:
                endpoint_failures += 1
                self.last_error = f"{model}: {type(exc).__name__}: {exc}"

        self._free_cache = list(dict.fromkeys(result))
        self._free_cache_ts = time.monotonic()
        if not self._free_cache and all_models and endpoint_failures:
            self.last_error = f"free model metadata unavailable for {endpoint_failures}/{len(all_models)} models; paid catalogue remains available"
        return list(self._free_cache)

    def ordered_models(self, candidates: list[str] | None = None, allow_paid: bool = True, preferred: str | None = None) -> list[str]:
        """Free models first, then every paid model when paid fallback is enabled."""
        all_models = list(dict.fromkeys(candidates or self.models()))
        free = self.free_models(all_models)
        free_set = set(free)
        ordered_free = list(free)
        if preferred and preferred in free_set:
            ordered_free = [preferred, *[m for m in ordered_free if m != preferred]]
        if not allow_paid:
            return ordered_free
        paid = [m for m in all_models if m not in free_set]
        if preferred and preferred in paid:
            paid = [m for m in paid if m != preferred] + [preferred]
        return ordered_free + paid

    def health(self, model: str) -> tuple[bool, str]:
        if not self.configured:
            return False, "API key not configured"
        if not model:
            return False, "model not selected"
        try:
            result = self._request(
                "POST", f"{BASE_URL}/chat/completions",
                {"model": model, "messages": [{"role": "user", "content": "Ответь OK"}], "max_tokens": 1, "temperature": 0, "provider": {"allow_fallbacks": False}},
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

    def analyze(self, model: str, prompt: str, allow_paid: bool = True) -> str | None:
        """Try free models first, then every paid model if enabled."""
        if not self.configured:
            self.last_error = "API key not configured"
            return None
        candidates = self.ordered_models(allow_paid=allow_paid, preferred=model)
        if not candidates:
            self.last_error = "no RouterAI models available"
            return None
        errors: list[str] = []
        for candidate in candidates:
            try:
                result = self._request(
                    "POST", f"{BASE_URL}/chat/completions",
                    {"model": candidate, "messages": [
                        {"role": "system", "content": "Ты аналитик безопасности VPS. Отвечай по-русски."},
                        {"role": "user", "content": prompt},
                    ], "temperature": 0, "max_tokens": 500, "provider": {"allow_fallbacks": False}},
                )
                content = ((result.get("choices") or [{}])[0].get("message") or {}).get("content")
                if content:
                    self.last_error = ""
                    self.last_model = candidate
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
        self.last_error = "; ".join(errors[-8:]) or "no RouterAI models available"
        return None
