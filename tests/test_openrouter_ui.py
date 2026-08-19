import importlib


def test_openrouter_ui_module_imports():
    module = importlib.import_module("xfi_guard.openrouter_ui")
    assert callable(module.install_openrouter_handlers)
    assert callable(module.openrouter_menu)


def test_openrouter_menu_contains_sync_controls():
    module = importlib.import_module("xfi_guard.openrouter_ui")
    markup = module.openrouter_menu()

    # Support both Telegram reply keyboards and inline keyboards. The UI
    # implementation has used both forms during the OpenRouter migration.
    rows = getattr(markup, "keyboard", None)
    if rows is None:
        rows = getattr(markup, "inline_keyboard", None)

    assert rows is not None
    labels = {
        getattr(button, "text", "")
        for row in rows
        for button in row
    }
    assert "🟣 OpenRouter" in labels
    assert "🔄 Синхронизировать AI" in labels
    assert "🧪 Проверить OpenRouter" in labels
