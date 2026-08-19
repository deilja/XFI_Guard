import inspect

from xfi_guard import bot


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


def test_main_menu_buttons_have_handlers_in_bot_source():
    source = inspect.getsource(bot.build_dispatcher)
    for label in _labels(bot.main_kb()):
        if label in {"⬅️ Главное меню"}:
            continue
        assert label in source, f"Нет обработчика/ссылки для кнопки {label}"
