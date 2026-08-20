"""RouterAI adapter for XFI Guard.

RouterAI exposes an OpenAI-compatible API. The adapter prefers verified free
chat-capable models and can fall back to paid chat models when explicitly
allowed by the XFI Guard settings.
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

    def _raw_models(self) -> list[str]:
        if not self.configured:
            return []
        try:
            data = self._request("GET", f"{BASE_URL}/models")
            return [str(item.get("id")) for item in data.get("data", []) if item.get("id")]
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []

    @staticmethod
    def _is_chat_endpoint(endpoint: dict) -> bool:
        apis = {str(x).lower() for x in (endpoint.get("supported_apis") or [])}
        input_modalities = {str(x).lower() for x in ((endpoint.get("architecture") or {}).get("input_modalities") or [])}
        output_modalities = {str(x).lower() for x in ((endpoint.get("architecture") or {}).get("output_modalities") or [])}
        return "chat" in apis and (not input_modalities or "text" in input_modalities) and (not output_modalities or "text" in output_modalities)

    def _endpoint_info(self, model: str) -> list[dict]:
        if "/" not in model:
            return []
        author, slug = model.split("/", 1)
        data = self._request("GET", f"{BASE_URL}/models/{author}/{slug}/endpoints")
        return list(((data.get("data") or {}).get("endpoints") or []))

    def _free_and_chat(self, candidates: list[str]) -> list[str]:
        result: list[str] = []
        for model in candidates:
            try:
                for endpoint in self._endpoint_info(model):
                    if not self._is_chat_endpoint(endpoint):
                        continue
                    pricing = endpoint.get("pricing") or {}
                    if self._zero(pricing.get("prompt")) and self._zero(pricing.get("completion")) and int(endpoint.get("status", 0) or 0) >= 0:
                        result.append(model)
                        break
            except error.HTTPError as exc:
                self.last_error = f"{model}: HTTP {exc.code}"
            except Exception as exc:
                self.last_error = f"{model}: {type(exc).__name__}: {exc}"
        return list(dict.fromkeys(result))

    def models(self) -> list[str]:
        """Return chat-capable models with free models ordered first."""
        raw = self._raw_models()
        if not raw:
            return []
        free = self._free_and_chat(raw)
        paid: list[str] = []
        for model in raw:
            if model in free:
                continue
            try:
                if any(self._is_chat_endpoint(endpoint) for endpoint in self._endpoint_info(model)):
                    paid.append(model)
            except error.HTTPError as exc:
                self.last_error = f"{model}: HTTP {exc.code}"
            except Exception as exc:
                self.last_error = f"{model}: {type(exc).__name__}: {exc}"
        return list(dict.fromkeys([*free, *paid]))

    def free_models(self, candidates: list[str] | None = None) -> list[str]:
        """Return only models with a working text-chat endpoint priced at zero."""
        if not self.configured:
            return []
        return self._free_and_chat(candidates or self._raw_models())

    @staticmethod
    def _zero(value) -> bool:
        try:
            return float(value or 0) == 0.0
        except (TypeError, ValueError):
            return False

    def health(self, model: str) -> tuple[bool, str]:
        """Probe a selected chat model with a minimal completion."""
        if not self.configured:
            return False, "API key not configured"
        try:
            result = self._request("POST", f"{BASE_URL}/chat/completions", {"model": model, "messages": [{"role": "user", "content": "Ответь OK"}], "max_tokens": 8, "temperature": 0, "provider": {"allow_fallbacks": False}})
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
        """Analyze using the selected RouterAI chat model."""
        if not self.configured:
            self.last_error = "API key not configured"
            return None
        try:
            result = self._request("POST", f"{BASE_URL}/chat/completions", {"model": model, "messages": [{"role": "system", "content": "Ты аналитик безопасности VPS. Отвечай по-русски."}, {"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 500, "provider": {"allow_fallbacks": False}})
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
