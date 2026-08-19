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
