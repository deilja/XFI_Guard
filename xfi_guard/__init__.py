"""XFI Guard package."""

__version__ = "1.1.0"


def _install_ai_analyzer_compat() -> None:
    """Expose a stable direct-analysis API with provider fallback."""
    from .ai import AIAnalyzer

    def _analyze_groq(self, event):
        prompt = self._prompt(event) if isinstance(event, dict) else str(event)
        model = self.groq_model
        if not model or not self.groq_key:
            return None
        return self._call("groq", model, prompt)

    def analyze(self, event):
        """Run one AI request using configured providers in free-first order.

        The method intentionally returns the provider's raw text. Consensus
        analysis remains available through ``analyze_consensus``.
        """
        prompt = self._prompt(event) if isinstance(event, dict) else str(event)
        configured = list(self.available_providers())
        if not configured:
            self.last_error = "AI-провайдеры не настроены"
            return None

        order = []
        for provider in [self.provider, "gemini", "groq", "openrouter", "routerai"]:
            if provider in configured and provider not in order:
                order.append(provider)

        errors = []
        for provider in order:
            try:
                if provider == "groq":
                    result = self._analyze_groq(event)
                    if result:
                        self.last_provider = provider
                        self.last_model = self.groq_model
                        self.last_error = ""
                        return result
                    provider_error = self.last_provider_errors.get(provider, "")
                    if provider_error:
                        errors.append(provider_error)
                    continue

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
                    else:
                        result = self._call(provider, model, prompt)
                    if result:
                        self.last_provider = provider
                        self.last_model = getattr(self.routerai, "last_model", "") or model
                        self.last_error = ""
                        return result

                provider_error = self.last_provider_errors.get(provider, "")
                if provider_error:
                    errors.append(provider_error)
            except Exception as exc:
                message = f"{provider}: {type(exc).__name__}: {exc}"
                self.last_provider_errors[provider] = message
                errors.append(message)

        self.last_error = "; ".join(errors[-4:]) or "all AI providers failed"
        return None

    AIAnalyzer._analyze_groq = _analyze_groq
    AIAnalyzer.analyze = analyze


_install_ai_analyzer_compat()
