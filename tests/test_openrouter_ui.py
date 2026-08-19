import importlib


def test_openrouter_ui_module_imports():
    module = importlib.import_module("xfi_guard.openrouter_ui")
    assert callable(module.install_openrouter_handlers)
    assert callable(module.openrouter_menu)


def test_openrouter_menu_contains_sync_controls():
    module = importlib.import_module("xfi_guard.openrouter_ui")
    keyboard = module.openrouter_menu().keyboard
    labels = {button.text for row in keyboard for button in row}
    assert "🟣 OpenRouter" in labels
    assert "🔄 Синхронизировать AI" in labels
    assert "🧪 Проверить OpenRouter" in labels
