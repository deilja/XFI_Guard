"""Unified AI provider interface for XFI Guard."""
from __future__ import annotations
import ipaddress, json, os
from urllib import request, error
from .gemini import GeminiAnalyzer
from .ai_store import load

class AIAnalyzer:
    def __init__(self, provider: str | None = None):
        cfg = load()
        self.provider = (provider or cfg.get("provider") or os.getenv("XFI_GUARD_AI_PROVIDER", "gemini")).lower()
        self.gemini = GeminiAnalyzer(api_key=cfg.get("gemini_key") or None, model=cfg.get("gemini_model") or None)
        self.groq_key = cfg.get("groq_key") or os.getenv("XFI_GUARD_GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
        self.groq_model = cfg.get("groq_model") or os.getenv("XFI_GROQ_MODEL") or os.getenv("XFI_GUARD_GROQ_MODEL", "openai/gpt-oss-20b")
        self.last_error = ""

    def enabled(self) -> bool:
        return self.gemini.enabled() if self.provider == "gemini" else self.provider == "groq" and bool(self.groq_key)

    def _groq_request(self, url: str, body: dict | None = None):
        headers = {"Authorization": f"Bearer {self.groq_key}", "Content-Type": "application/json", "User-Agent": "XFI-Guard/1.0"}
        data = json.dumps(body).encode() if body is not None else None
        req = request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
        try:
            with request.urlopen(req, timeout=20) as response:
                return json.loads(response.read().decode()), response.status
        except error.HTTPError as exc:
            self.last_error = f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}"
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
        return None, 0

    def list_groq_models(self) -> list[dict]:
        if not self.groq_key:
            self.last_error = "API-ключ Groq не настроен"; return []
        payload, _ = self._groq_request("https://api.groq.com/openai/v1/models")
        if not payload or not isinstance(payload.get("data"), list):
            self.last_error = self.last_error or "Groq API вернул некорректный ответ"; return []
        return sorted(({"id": x.get("id"), "owned_by": x.get("owned_by", "")} for x in payload["data"] if x.get("id")), key=lambda x: x["id"])

    def analyze(self, event: dict) -> str | None:
        if self.provider == "gemini":
            try:
                result = self.gemini.analyze(event)
                if result is None: self.last_error = "Gemini не вернул ответ или ключ/модель недействительны"
                return result
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"; return None
        if self.provider != "groq" or not self.groq_key:
            self.last_error = "Groq не выбран или API-ключ не настроен"; return None
        prompt = "Проанализируй событие безопасности VPS. Ответь кратко на русском языке: риск, объяснение, рекомендуемое действие. Не выполняй команды.\n" + json.dumps(event, ensure_ascii=False)
        body = {"model": self.groq_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 500}
        payload, _ = self._groq_request("https://api.groq.com/openai/v1/chat/completions", body)
        try: return payload["choices"][0]["message"]["content"] if payload else None
        except (KeyError, IndexError, TypeError):
            self.last_error = self.last_error or "Groq API вернул ответ без текста модели"; return None

    def recommend_block_ips(self, events: list[dict]) -> list[dict]:
        """Return AI recommendations only; never changes the firewall."""
        candidates, seen = [], set()
        for event in events:
            ip = str(event.get("ip") or "").strip()
            if not ip or ip in seen: continue
            try:
                parsed = ipaddress.ip_address(ip)
                if parsed.version == 4 and parsed.is_global:
                    candidates.append({"ip": ip, "severity": event.get("severity", "unknown"), "event_type": event.get("event_type", "unknown"), "message": event.get("message", "")}); seen.add(ip)
            except ValueError: continue
        if not candidates or not self.enabled(): return []
        prompt = ("Ты аналитик безопасности XFI Guard. Оцени только перечисленные публичные IPv4. "
                  "Выбери максимум 5 адресов, которые обоснованно рекомендуется заблокировать. "
                  "Никогда не придумывай IP. Верни ТОЛЬКО JSON-объект с ключом recommendations, "
                  "где значение — массив объектов {ip, reason, confidence}. Блокировка не выполняется автоматически.\n\n" + json.dumps(candidates, ensure_ascii=False))
        try:
            if self.provider == "gemini":
                result = self.gemini.analyze({"event_type": "block_recommendation", "message": prompt})
            else:
                body = {"model": self.groq_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 700, "response_format": {"type": "json_object"}}
                payload, _ = self._groq_request("https://api.groq.com/openai/v1/chat/completions", body)
                result = payload["choices"][0]["message"]["content"] if payload else None
            data = json.loads(result) if result else {}
            data = data.get("recommendations", []) if isinstance(data, dict) else []
            allowed = {x["ip"] for x in candidates}; out = []
            for item in data[:5]:
                ip = str(item.get("ip", "")) if isinstance(item, dict) else ""
                if ip in allowed:
                    try: confidence = float(item.get("confidence", 0) or 0)
                    except (TypeError, ValueError): confidence = 0.0
                    out.append({"ip": ip, "reason": str(item.get("reason", "Подозрительная активность")), "confidence": confidence})
            return out
        except Exception as exc:
            self.last_error = f"Рекомендации AI: {type(exc).__name__}: {exc}"; return []
