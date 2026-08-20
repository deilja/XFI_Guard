from unittest.mock import patch

from xfi_guard.routerai import RouterAIAdapter


def test_routerai_excludes_media_models_from_chat_pool():
    assert RouterAIAdapter._is_chat_model("qwen/qwen3.7-plus")
    assert not RouterAIAdapter._is_chat_model("alibaba/happyhorse-1.0")
    assert not RouterAIAdapter._is_chat_model("google/gemini-3.1-flash-image")
    assert not RouterAIAdapter._is_chat_model("openai/sora-2-pro")


def test_routerai_free_first_and_paid_policy():
    adapter = RouterAIAdapter("test-key")
    models = ["free/provider-chat", "paid/provider-chat", "alibaba/happyhorse-1.0"]

    with patch.object(adapter, "models", return_value=models), patch.object(
        adapter, "free_models", return_value=["free/provider-chat"]
    ):
        assert adapter.ordered_models(allow_paid=False) == ["free/provider-chat"]
        assert adapter.ordered_models(allow_paid=True) == [
            "free/provider-chat",
            "paid/provider-chat",
        ]


def test_routerai_uses_paid_model_only_when_no_free_model_exists():
    adapter = RouterAIAdapter("test-key")
    models = ["paid/provider-chat"]

    with patch.object(adapter, "models", return_value=models), patch.object(
        adapter, "free_models", return_value=[]
    ):
        with patch.object(adapter, "_request", return_value={
            "choices": [{"message": {"content": "OK"}}]
        }) as request:
            assert adapter.analyze("paid/provider-chat", "test", allow_paid=False) is None
            request.assert_not_called()

        with patch.object(adapter, "_request", return_value={
            "choices": [{"message": {"content": "OK"}}]
        }) as request:
            assert adapter.analyze("paid/provider-chat", "test", allow_paid=True) == "OK"
            assert request.call_args.args[2]["model"] == "paid/provider-chat"
