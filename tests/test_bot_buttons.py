import inspect

from xfi_guard import bot
from xfi_guard import xui_ui


def _labels(markup):
    rows = getattr(markup, "keyboard", None) or getattr(markup, "inline_keyboard", None) or []
    return {getattr(button, "text", "") for row in rows for button in row}


def test_main_menu_exposes_operational_controls():
    labels = _labels(bot.main_kb())
    assert "📋 События" in labels
    assert "⚙️ 3X-UI" in labels
    assert "🤖 AI" in labels
    assert "🔄 Обновить XFI Guard" in labels
    assert "⚡ Принудительное обновление" in labels


def test_main_menu_buttons_have_handlers():
    """Every main-menu control is handled either in bot.py or a delegated UI module."""
    bot_source = inspect.getsource(bot.build_dispatcher)
    xui_source = inspect.getsource(xui_ui.install_xui_handlers)
    sources = bot_source + "\n" + xui_source
    delegated = {"⚙️ 3X-UI"}
    for label in _labels(bot.main_kb()):
        if label in {"⬅️ Главное меню"}:
            continue
        assert label in sources or label in delegated, f"Нет обработчика/ссылки для кнопки {label}"


def test_3xui_menu_is_registered_from_dispatcher():
    source = inspect.getsource(bot.build_dispatcher)
    assert "install_xui_handlers(dp)" in source
    assert "⚙️ 3X-UI" in inspect.getsource(xui_ui.install_xui_handlers)
