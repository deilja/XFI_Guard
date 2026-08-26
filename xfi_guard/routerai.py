"""RouterAI adapter for XFI Guard."""
from __future__ import annotations
import json, os, time
from urllib import error, request

BASE_URL = "https://routerai.ru/api/v1"


class RouterAIAdapter:
    provider = "routerai"

    def __init__(self, api_key=None, timeout=20.0):
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
        self._models_cache = []
        self._models_meta_cache = {}
        self._models_cache_ts = 0.0
        self._free_cache = []
        self._free_cache_ts = 0.0
        self.cache_ttl = 300.0

    @property
    def configured(self):
        return bool(self.api_key)

    @classmethod
    def _is_chat_model(cls, model):
        s = str(model or "").lower()
        return bool(s) and not any(x in s for x in ("embedding", "moderation", "whisper", "tts", "speech", "image", "vision", "audio", "happyhorse", "sora"))

    @classmethod
    def _endpoint_items(cls, data):
        """Return endpoint/model records from RouterAI's several response shapes."""
        if not isinstance(data, dict):
            return []
        root = data.get("data", data)
        if isinstance(root, dict):
            for key in ("endpoints", "models", "data", "items"):
                value = root.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]
            return [root] if root.get("id") else []
        if isinstance(root, list):
            return [x for x in root if isinstance(x, dict)]
        return []

    def _request(self, method, url, payload=None):
        headers = {"Accept": "application/json", "User-Agent": "XFI-Guard/1.9"}
        if self.api_key:
            try:
                self.api_key.encode("ascii")
            except UnicodeEncodeError as exc:
                self.last_error = "API key contains non-ASCII characters"
                raise RuntimeError(self.last_error) from exc
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = request.Request(url, data=data, headers=headers, method=method)
        with request.urlopen(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode())

    def models(self, force=False):
        if not self.configured:
            return []
        if not force and self._models_cache and time.monotonic() - self._models_cache_ts < self.cache_ttl:
            return list(self._models_cache)
        try:
            data = self._request("GET", f"{BASE_URL}/models")
            result, meta = [], {}
            for item in self._endpoint_items(data):
                if item.get("id") and self._is_chat_model(item["id"]):
                    model = str(item["id"])
                    result.append(model)
                    meta[model] = item
            self._models_cache = list(dict.fromkeys(result))
            self._models_meta_cache = meta
            self._models_cache_ts = time.monotonic()
            return list(self._models_cache)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return list(self._models_cache)

    @classmethod
    def _zero(cls, value):
        if isinstance(value, dict):
            value = value.get("value", value.get("amount", value.get("price")))
        if value is None:
            return True
        if isinstance(value, str):
            value = value.strip().lower().replace("₽", "").replace("rub", "")
            if value in {"", "0", "0.0", "0.00", "0.000000", "free", "бесплатно"}:
                return True
        try:
            return float(value) == 0.0
        except (TypeError, ValueError):
            return False

    @classmethod
    def _pricing_is_free(cls, pricing):
        if not isinstance(pricing, dict):
            return False
        if pricing.get("free") is True:
            return True
        return cls._zero(pricing.get("prompt", pricing.get("input"))) and cls._zero(pricing.get("completion", pricing.get("output")))

    @classmethod
    def _model_is_free(cls, item):
        if not isinstance(item, dict):
            return False
        if any(item.get(k) is True for k in ("free", "is_free", "free_tier")):
            return True
        return cls._pricing_is_free(item.get("pricing"))

    def free_models(self, candidates=None, force=False):
        all_models = list(dict.fromkeys(candidates or self.models(force=force)))
        result = []
        for model in all_models:
            meta = self._models_meta_cache.get(model) or {}
            if self._model_is_free(meta):
                result.append(model)
        self._free_cache = list(dict.fromkeys(result))
        self._free_cache_ts = time.monotonic()
        return list(self._free_cache)

    def ordered_models(self, candidates=None, allow_paid=True, preferred=None):
        all_models = [m for m in dict.fromkeys(candidates or self.models()) if self._is_chat_model(m)]
        free = self.free_models(all_models)
        free_set = set(free)
        ordered = [preferred, *[m for m in free if m != preferred]] if preferred in free_set else free
        if not allow_paid:
            return ordered
        paid = [m for m in all_models if m not in free_set and m != preferred]
        return ordered + ([preferred] if preferred in paid else []) + paid

    def health(self, model):
        if not self.configured:
            return False, "API key not configured"
        if not model:
            return False, "model not selected"
        try:
            r = self._request("POST", f"{BASE_URL}/chat/completions", {"model": model, "messages": [{"role": "user", "content": "Ответь OK"}], "max_tokens": 1, "temperature": 0})
            c = ((r.get("choices") or [{}])[0].get("message") or {}).get("content")
            return bool(c), "" if c else "empty response"
        except error.HTTPError as exc:
            return False, f"HTTP {exc.code}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def analyze(self, model, prompt, allow_paid=False):
        if not self.configured:
            return None
        candidates = self.ordered_models(allow_paid=allow_paid, preferred=model)
        if allow_paid and model and self._is_chat_model(model) and model not in candidates:
            candidates.insert(0, model)
        if not candidates:
            self.last_error = "no RouterAI chat models available"
            return None
        for candidate in candidates:
            try:
                result = self._request("POST", f"{BASE_URL}/chat/completions", {"model": candidate, "messages": [{"role": "system", "content": "Ты аналитик безопасности VPS. Отвечай по-русски."}, {"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 500})
                content = ((result.get("choices") or [{}])[0].get("message") or {}).get("content")
                if content:
                    self.last_error = ""
                    self.last_model = candidate
                    return str(content)
            except Exception as exc:
                self.last_error = f"{candidate}: {type(exc).__name__}: {exc}"
        return None
