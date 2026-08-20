"""RouterAI adapter for XFI Guard.

RouterAI exposes an OpenAI-compatible API. This adapter is intentionally
standalone so the main AI engine can opt into it without making paid requests
implicitly. A model is considered eligible only when it has at least one
working chat endpoint with explicitly zero prompt and completion pricing.
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

    @staticmethod
    def _is_free_chat_endpoint(endpoint: dict) -> bool:
        """Return whether an endpoint can serve free text chat requests."""
        pricing = endpoint.get("pricing") or {}
        if not (RouterAIAdapter._zero(pricing.get("prompt")) and RouterAIAdapter._zero(pricing.get("completion"))):
            return False
        try:
            if int(endpoint.get("status", 0) or 0) < 0:
                return False
        except (TypeError, ValueError):
            return False

        supported_apis = endpoint.get("supported_apis") or []
        if supported_apis and "chat" not in {str(x).lower() for x in supported_apis}:
            return False

        architecture = endpoint.get("architecture") or {}
        output_modalities = architecture.get("output_modalities") or []
        if output_modalities and "text" not in {str(x).lower() for x in output_modalities}:
            return False

        return True

    def free_models(self, candidates: list[str] | None = None) -> list[str]:
        """Return only models having an explicitly zero-cost text-chat endpoint."""
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
                if any(self._is_free_chat_endpoint(endpoint) for endpoint in endpoints):
                    result.append(model)
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

    @staticmethod
    def _content_from_response(result: dict) -> str | None:
        """Extract text from OpenAI-compatible RouterAI chat responses."""
        if not isinstance(result, dict):
            return None
        choices = result.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return None
        choice = choices[0]
        message = choice.get("message") or {}
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") in {"text", "output_text"} and item.get("text"):
                        parts.append(str(item["text"]))
                if parts:
                    return "\n".join(parts).strip()
            reasoning = message.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                return reasoning.strip()
        text = choice.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        return None

    def health(self, model: str) -> tuple[bool, str]:
        """Probe a model with one output token.

        The caller must first establish that the model has a zero-cost chat
        endpoint when enforcing the global free-only policy.
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
            content = self._content_from_response(result)
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
        """Analyze using a caller-approved free text-chat model only."""
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
            content = self._content_from_response(result)
            if not content:
                self.last_error = "empty response"
                return None
            self.last_error = ""
            return content
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
