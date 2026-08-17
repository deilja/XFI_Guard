"""XFI Guard package."""

__version__ = "0.1.0"

# Telegram UI: при переходе на новый экран предыдущее меню удаляется.
from . import menu_manager as _menu_manager  # noqa: F401,E402
