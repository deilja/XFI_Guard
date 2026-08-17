"""Unified AI provider interface for XFI Guard."""
from __future__ import annotations
import ipaddress, json, os
from urllib import request, error
from .gemini import GeminiAnalyzer
from .ai_store import load
from .attack_surface import collect_attack_surface

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
                if result is None:
                    self.last_error = self.gemini.last_error or "Gemini не вернул ответ"
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
        """Return AI recommendations from the full current attack surface."""
        candidates_by_ip: dict[str, dict] = {}
        for event in events:
            ip = str(event.get("ip") or "").strip()
            if not ip:
                continue
            try:
                parsed = ipaddress.ip_address(ip)
                if parsed.version != 4 or not parsed.is_global:
                    continue
                item = candidates_by_ip.setdefault(ip, {"ip": ip, "sources": [], "events": 0, "severity": "warning", "reason": ""})
                item["events"] += 1
                source = str(event.get("source") or event.get("event_type") or "events")
                if source not in item["sources"]: item["sources"].append(source)
                if event.get("severity") == "critical": item["severity"] = "critical"
                if event.get("reason") or event.get("message"): item["reason"] = str(event.get("reason") or event.get("message"))[:300]
            except ValueError:
                continue
        try:
            inventory = collect_attack_surface()
            for item in inventory.get("ips", []):
                ip = item.get("ip")
                if not ip: continue
                current = candidates_by_ip.setdefault(ip, {"ip": ip, "sources": [], "events": 0, "severity": "warning", "reason": ""})
                for source in item.get("sources", []):
                    if source not in current["sources"]: current["sources"].append(source)
                current["events"] = max(current["events"], int(item.get("events", 0) or 0))
                if item.get("severity") == "critical": current["severity"] = "critical"
                if item.get("reason"): current["reason"] = str(item["reason"])[:300]
        except Exception as exc:
            self.last_error = f"Сбор картины атак: {type(exc).__name__}: {exc}"
        candidates = list(candidates_by_ip.values())
        if not candidates or not self.enabled(): return []
        candidates.sort(key=lambda x: (x["severity"] != "critical", -len(x["sources"]), -x["events"]))
        prompt = ("Ты аналитик безопасности XFI Guard. Проанализируй ПОЛНУЮ текущую картину атак VPS. Учитывай источники fail2ban, ufw и ssh, число событий и повторяемость. Выбери максимум 5 адресов, которые обоснованно рекомендуется заблокировать. Не рекомендуй уже заблокированный UFW адрес повторно. Никогда не придумывай IP. Для каждого укажи reason и risk: low, medium, high или critical. Верни ТОЛЬКО JSON-объект {recommendations:[{ip,reason,risk,confidence}]}. Блокировка не выполняется автоматически. Ответ должен быть на русском языке.\n\n" + json.dumps(candidates, ensure_ascii=False))
        try:
            if self.provider == "gemini":
                result = self.gemini.analyze({"event_type": "full_attack_surface_recommendation", "message": prompt})
                if result is None: self.last_error = self.gemini.last_error or self.last_error
            else:
                body = {"model": self.groq_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 900, "response_format": {"type": "json_object"}}
                payload, _ = self._groq_request("https://api.groq.com/openai/v1/chat/completions", body)
                result = payload["choices"][0]["message"]["content"] if payload else None
            data = json.loads(result) if result else {}
            data = data.get("recommendations", []) if isinstance(data, dict) else []
            allowed = {x["ip"] for x in candidates}
            blocked = set()
            try:
                from .firewall import list_blocked_ips
                blocked = set(list_blocked_ips())
            except Exception: pass
            out = []
            for item in data[:5]:
                ip = str(item.get("ip", "")) if isinstance(item, dict) else ""
                if ip in allowed and ip not in blocked:
                    try: confidence = float(item.get("confidence", 0) or 0)
                    except (TypeError, ValueError): confidence = 0.0
                    risk = str(item.get("risk", "medium")).lower()
                    if risk not in {"low", "medium", "high", "critical"}: risk = "medium"
                    out.append({"ip": ip, "reason": str(item.get("reason", "Подозрительная активность")), "risk": risk, "confidence": confidence})
            return out
        except Exception as exc:
            self.last_error = f"Рекомендации AI: {type(exc).__name__}: {exc}"; return []
