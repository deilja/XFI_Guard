"""XFI Guard package."""

__version__ = "1.1.0"


def _install_ai_analyzer_compat() -> None:
    """Expose a stable direct-analysis API with provider fallback.

    Older integrations import ``AIAnalyzer`` and call ``analyze()`` directly.
    Keep that API compatible while preferring explicitly configured models and
    using model discovery only as an additional fallback. This is important
    when discovery is temporarily unavailable but a known working model is
    already configured.
    """
    from .ai import AIAnalyzer

    def _analyze_groq(self, event):
        prompt = self._prompt(event) if isinstance(event, dict) else str(event)
        model = self.groq_model
        if not model or not self.groq_key:
            return None
        return self._call("groq", model, prompt)

    def _configured_models(self, provider):
        """Return configured models before attempting network discovery."""
        if provider == "gemini":
            return [self.gemini_model] if self.gemini_model else []
        if provider == "groq":
            return [self.groq_model] if self.groq_model else []
        if provider == "openrouter":
            return [self.openrouter_model, *self.openrouter_models]
        if provider == "routerai":
            return [self.routerai_model, *self.routerai_models]
        return []

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
                    result = _analyze_groq(self, event)
                    if result:
                        self.last_provider = provider
                        self.last_model = self.groq_model
                        self.last_error = ""
                        return result
                    provider_error = self.last_provider_errors.get(provider, "")
                    if provider_error:
                        errors.append(provider_error)
                    continue

                # A configured model must remain usable even if model discovery
                # is temporarily unavailable. Discovery is only supplemental.
                configured_models = self._configured_models(provider)
                discovered_models = []
                if not configured_models:
                    discovered_models = self._models_for(provider)
                models = list(dict.fromkeys([
                    *configured_models,
                    *discovered_models,
                ]))
                models = [m for m in models if m]
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
