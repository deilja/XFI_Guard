import inspect

from xfi_guard import bot
from xfi_guard import xui_ui


def _labels(markup):
    rows = getattr(markup, "keyboard", None) or getattr(markup, "inline_keyboard", None) or []
    return {getattr(button, "text", "") for row in rows for button in row}


def test_main_menu_exposes_compact_operational_controls():
    labels = _labels(bot.main_kb())
    expected = {
        "📊 Статус", "🛡 Защита", "🌐 VPN/Xray", "🤖 AI", "🖥 VPS",
        "🌐 Кластер", "🚫 Блокировки", "📋 События", "⚙️ 3X-UI",
        "🔄 Проверка", "🔄 Обновить", "❓ Помощь",
    }
    assert labels == expected


def test_main_menu_buttons_have_handlers():
    """Every compact main-menu button has a direct handler or delegated module."""
    source = inspect.getsource(bot.build_dispatcher)
    for label in _labels(bot.main_kb()):
        assert label in source, f"Нет обработчика для кнопки {label}"


def test_no_legacy_main_menu_labels():
    labels = _labels(bot.main_kb())
    legacy = {"🔄 Обновить XFI Guard", "⚡ Принудительное обновление", "🔐 Безопасность"}
    assert not labels.intersection(legacy)


def test_3xui_menu_is_registered_from_dispatcher():
    source = inspect.getsource(bot.build_dispatcher)
    assert "install_xui_handlers(dp)" in source
    assert "⚙️ 3X-UI" in inspect.getsource(xui_ui.install_xui_handlers)
