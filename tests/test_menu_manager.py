import pytest

from xfi_guard import menu_manager


class _ExpiredCallbackError(Exception):
    pass


class _Callback:
    def __init__(self, error):
        self.error = error

    async def answer(self):
        raise self.error


@pytest.mark.asyncio
async def test_safe_callback_answer_ignores_expired_query(monkeypatch):
    monkeypatch.setattr(menu_manager, "TelegramBadRequest", _ExpiredCallbackError)
    callback = _Callback(
        _ExpiredCallbackError(
            "Telegram server says - Bad Request: query is too old and response timeout expired or query ID is invalid"
        )
    )

    assert await menu_manager._safe_callback_answer(callback) is False


@pytest.mark.asyncio
async def test_safe_callback_answer_reraises_other_bad_request(monkeypatch):
    monkeypatch.setattr(menu_manager, "TelegramBadRequest", _ExpiredCallbackError)
    callback = _Callback(_ExpiredCallbackError("Bad Request: message is not modified"))

    with pytest.raises(_ExpiredCallbackError, match="message is not modified"):
        await menu_manager._safe_callback_answer(callback)


def test_inline_menu_adds_bottom_navigation():
    markup = menu_manager.InlineMenuMarkup(keyboard=[["📊 Статус"]])
    texts = [button.text for row in markup.inline_keyboard for button in row]
    assert texts[-2:] == ["◀️ Назад", "🏠 Главная"]


def test_main_menu_does_not_duplicate_bottom_navigation():
    markup = menu_manager.InlineMenuMarkup(
        keyboard=[["📊 Статус", "🚫 Блокировка IP"], ["◀️ Назад", "🏠 Главная"]]
    )
    texts = [button.text for row in markup.inline_keyboard for button in row]
    assert texts.count("◀️ Назад") == 0
    assert texts.count("🏠 Главная") == 0
