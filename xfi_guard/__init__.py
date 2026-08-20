"""XFI Guard package."""

__version__ = "1.1.0"

# Keep all configured AI providers available, including RouterAI.
# RouterAI itself enforces the free-first / paid-fallback policy.
try:
    from . import ai as _ai

    _ai.PROVIDERS = ("gemini", "groq", "openrouter", "routerai")
    _ai.DEFAULT_WEIGHTS = {p: 1.0 for p in _ai.PROVIDERS}

    # Backward-compatible public API. Older callers used AIAnalyzer.analyze(),
    # while the consensus engine exposes analyze_consensus().
    if not hasattr(_ai.AIAnalyzer, "analyze"):
        def _analyze(self, event):
            return self.analyze_consensus(event)

        _ai.AIAnalyzer.analyze = _analyze
except Exception:
    # Package import must remain resilient when optional AI dependencies are
    # unavailable during installation or diagnostics.
    pass
