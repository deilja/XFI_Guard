"""XFI Guard package."""

__version__ = "1.1.0"

# Telegram UI: при переходе на новый экран предыдущее меню удаляется.
from . import menu_manager as _menu_manager  # noqa: F401,E402

# Runtime AI failover audit is installed once at package import.
from .ai import AIAnalyzer as _AIAnalyzer  # noqa: E402
from .ai_runtime import install as _install_ai_runtime  # noqa: E402
_install_ai_runtime(_AIAnalyzer)
