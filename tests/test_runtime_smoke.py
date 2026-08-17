import importlib


def test_bot_module_imports():
    module = importlib.import_module("xfi_guard.bot")
    assert hasattr(module, "build_dispatcher")


def test_bot_dispatcher_builder():
    module = importlib.import_module("xfi_guard.bot")
    dispatcher = module.build_dispatcher()
    assert dispatcher is not None
    assert hasattr(dispatcher, "start_polling")
