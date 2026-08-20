"""XFI Guard package."""

__version__ = "1.1.0"


def _install_ai_analyzer_compat() -> None:
    """Expose a stable direct-analysis API with provider fallback."""
    from .ai import AIAnalyzer

    if hasattr(AIAnalyzer, "analyze"):
        return

    def analyze(self, event):
        self._sync_config()
        if isinstance(event, dict):
            return self.analyze_consensus(event)

        prompt = str(event)
        configured = self.available_providers()
        if not configured:
            self.last_error = "no AI providers configured"
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

            if provider == "routerai":
                result = self.routerai.analyze(
                    models[0],
                    prompt,
                    allow_paid=self.routerai_allow_paid,
                )
            else:
                result = None
                for model in models:
                    result = self._call(provider, model, prompt)
                    if result:
                        break

            if result:
                self.last_provider = provider
                if provider == "routerai":
                    self.last_model = self.routerai.last_model or models[0]
                self.last_error = ""
                return result

            provider_error = self.last_provider_errors.get(provider, "")
            if provider_error:
                errors.append(provider_error)

        self.last_error = "; ".join(errors[-4:]) or "all AI providers failed"
        return None

    AIAnalyzer.analyze = analyze


_install_ai_analyzer_compat()
