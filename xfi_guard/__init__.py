"""XFI Guard package."""

__version__ = "1.1.0"


def _install_ai_analyzer_compat() -> None:
    """Expose a stable direct-analysis API with provider fallback."""
    from .ai import AIAnalyzer

    def analyze(self, event):
        self._sync_config()
        prompt = self._prompt(event) if isinstance(event, dict) else str(event)
        configured = self.available_providers()
        if not configured:
            self.last_error = "AI-провайдеры не настроен"
            return None

        order = []
        for provider in [self.provider, "gemini", "groq", "openrouter", "routerai"]:
            if provider in configured and provider not in order:
                order.append(provider)

        errors = []
        for provider in order:
            models = self._models_for(provider)
            if not models:
                errors.append(f"{provider}: no model available")
                continue

            for model in models:
                if provider == "routerai":
                    result = self.routerai.analyze(
                        model,
                        prompt,
                        allow_paid=self.routerai_allow_paid,
                    )
                    if result:
                        self.last_provider = provider
                        self.last_model = self.routerai.last_model or model
                        self.last_error = ""
                        return result
                else:
                    result = self._call(provider, model, prompt)
                    if result:
                        self.last_provider = provider
                        self.last_model = model
                        self.last_error = ""
                        return result

            provider_error = self.last_provider_errors.get(provider, "")
            if provider_error:
                errors.append(provider_error)

        self.last_error = "; ".join(errors[-4:]) or "all AI providers failed"
        return None

    AIAnalyzer.analyze = analyze


_install_ai_analyzer_compat()
