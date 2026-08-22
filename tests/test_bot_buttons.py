import inspect

from xfi_guard import bot
from xfi_guard import xui_ui, cluster_ui, defense_ui


def _labels(markup):
    rows = getattr(markup, "keyboard", None) or getattr(markup, "inline_keyboard", None) or []
    return {getattr(button, "text", "") for row in rows for button in row}


def test_main_menu_exposes_compact_operational_controls():
    assert _labels(bot.main_kb()) == {
        "📊 Статус", "🛡 Защита", "🌐 VPN/Xray", "🤖 AI", "🖥 VPS",
        "🌐 Кластер", "🚫 Блокировки", "📋 События", "⚙️ 3X-UI",
        "🔄 Проверка", "🔄 Обновить", "❓ Помощь",
    }


def test_main_menu_buttons_have_handlers_or_delegates():
    source = inspect.getsource(bot.build_dispatcher)
    delegated = {
        "⚙️ 3X-UI": inspect.getsource(xui_ui.install_xui_handlers),
        "🌐 Кластер": inspect.getsource(cluster_ui.install_cluster_handlers),
        "🛡 Защита": inspect.getsource(defense_ui.install_defense_handlers),
    }
    for label in _labels(bot.main_kb()):
        assert label in source or label in delegated.get(label, ""), f"Нет обработчика для кнопки {label}"


def test_no_legacy_main_menu_labels():
    labels = _labels(bot.main_kb())
    assert not labels.intersection({"🔄 Обновить XFI Guard", "⚡ Принудительное обновление", "🔐 Безопасность"})


def test_delegated_ui_modules_are_registered_once():
    source = inspect.getsource(bot.build_dispatcher)
    assert source.count("install_xui_handlers(dp)") == 1
    assert source.count("install_cluster_handlers(dp,ADMIN_IDS,main_kb)") == 1
    assert source.count("install_defense_handlers(dp)") == 1
