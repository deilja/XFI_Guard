import importlib


def test_openrouter_ui_module_imports():
    module = importlib.import_module("xfi_guard.openrouter_ui")
    assert callable(module.install_openrouter_handlers)


def test_openrouter_ui_is_legacy_noop():
    module = importlib.import_module("xfi_guard.openrouter_ui")
    assert module.install_openrouter_handlers(None) is None
