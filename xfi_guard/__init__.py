"""XFI Guard package."""

__version__ = "1.1.0"


def _install_ai_analyzer_compat() -> None:
    """Expose a stable direct-analysis API without changing the consensus engine."""
    from .ai import AIAnalyzer

    if hasattr(AIAnalyzer, "analyze"):
        return

    def analyze(self, event):
        self._sync_config()
        if isinstance(event, dict):
            return self.analyze_consensus(event)

        prompt = str(event)
        provider = self.provider if self._has_key(self.provider) else ((self.available_providers() or [None])[0])
        if not provider:
            self.last_error = "no AI providers configured"
            return None

        models = self._models_for(provider)
        model = models[0] if models else ""
        if not model:
            self.last_error = f"{provider}: no model available"
            return None

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
            self.last_model = model
        return result

    AIAnalyzer.analyze = analyze


_install_ai_analyzer_compat()
