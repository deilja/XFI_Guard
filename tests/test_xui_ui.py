from pathlib import Path

from xfi_guard import xui_api_store
from xfi_guard import xui_ui


def test_xui_menu_contains_all_controls():
    markup = xui_ui.xui_menu()
    rows = getattr(markup, "keyboard", None) or getattr(markup, "inline_keyboard", None)
    assert rows is not None
    labels = {getattr(button, "text", "") for row in rows for button in row}
    assert {"➕ Добавить 3X-UI", "📋 Список 3X-UI", "🧪 Проверить 3X-UI", "🗑 Удалить 3X-UI"} <= labels


def test_xui_store_roundtrip(tmp_path: Path):
    path = str(tmp_path / "xui.json")
    item = xui_api_store.upsert("Germany", "https://panel.example.com", "secret", path)
    assert item["name"] == "Germany"
    assert xui_api_store.get("Germany", path)["token"] == "secret"
    assert xui_api_store.remove("Germany", path) is True
    assert xui_api_store.load(path) == []


def test_xui_store_rejects_invalid_url(tmp_path: Path):
    path = str(tmp_path / "xui.json")
    try:
        xui_api_store.upsert("bad", "not-a-url", "", path)
    except ValueError as exc:
        assert "URL" in str(exc)
    else:
        raise AssertionError("invalid URL was accepted")
