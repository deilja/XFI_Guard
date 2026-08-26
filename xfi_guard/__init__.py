"""XFI Guard package."""

__version__ = "1.1.0"


def _install_ai_analyzer_compat() -> None:
    """Keep the public analyzer API compatible with direct prompts and config sync."""
    from .ai import AIAnalyzer
    from .ai_store import load

    # Consensus remains the path for structured security events. A plain string is
    # the public direct-analysis API and must return the provider response verbatim.
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
            result = self.routerai.analyze(model, prompt, allow_paid=self.routerai_allow_paid)
        else:
            result = self._call(provider, model, prompt)
        if result:
            self.last_provider, self.last_model = provider, model
        return result

    AIAnalyzer.analyze = analyze

    # Model discovery is allowed to discover available models, but it must not
    # silently replace an explicitly configured OpenRouter model/list. This is
    # especially important during sync and keeps the admin UI deterministic.
    original_discover = AIAnalyzer.discover_models

    def discover_models(self, force=False):
        result = original_discover(self, force=force)
        try:
            cfg = load()
            configured_model = str(cfg.get("openrouter_model") or "").strip()
            configured_models = cfg.get("openrouter_models") or ()
            if configured_model:
                self.openrouter_model = configured_model
            if isinstance(configured_models, (list, tuple)):
                self.openrouter_models = [str(x).strip() for x in configured_models if str(x).strip()]
            elif configured_models:
                self.openrouter_models = [x.strip() for x in str(configured_models).split(",") if x.strip()]
        except Exception:
            pass
        return result

    AIAnalyzer.discover_models = discover_models


_install_ai_analyzer_compat()
