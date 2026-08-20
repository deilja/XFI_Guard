"""XFI Guard package."""

__version__ = "1.1.0"

# XFI Guard intentionally operates only with free-capable AI providers.
# Keep the compatibility implementation in ai.py, but prevent removed paid
# providers from entering consensus, health checks, or provider selection.
try:
    from . import ai as _ai
    _ai.PROVIDERS = ("gemini", "groq", "openrouter")
    _ai.DEFAULT_WEIGHTS = {p: 1.0 for p in _ai.PROVIDERS}
except Exception:
    pass
