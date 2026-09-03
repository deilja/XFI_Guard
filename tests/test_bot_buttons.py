import inspect
from xfi_guard import bot
from xfi_guard import defense_ui

def _labels(markup):
    rows=getattr(markup,"keyboard",None) or getattr(markup,"inline_keyboard",None) or []
    return {getattr(button,"text","") for row in rows for button in row}

def test_main_menu_exposes_operational_controls():
    assert _labels(bot.main_kb()) == {"📊 Статус","🛡 Защита","🌐 VPN/Xray","🤖 AI","🖥 VPS","🚫 Блокировки","📋 События","🔄 Проверка","🔄 Обновить бота","❓ Помощь"}

def test_main_menu_buttons_have_handlers_or_delegates():
    source=inspect.getsource(bot.build_dispatcher)
    delegated={"🛡 Защита":inspect.getsource(defense_ui.install_defense_handlers)}
    for label in _labels(bot.main_kb()): assert label in source or label in delegated.get(label,"")

def test_no_legacy_main_menu_labels():
    labels=_labels(bot.main_kb())
    assert not labels.intersection({"🌐 Кластер","⚙️ 3X-UI","🔄 Обновить XFI Guard","⚡ Принудительное обновление","🔐 Безопасность"})

def test_defense_registered_once():
    source=inspect.getsource(bot.build_dispatcher)
    assert source.count("install_defense_handlers(dp)")==1
