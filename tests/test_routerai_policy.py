from xfi_guard.routerai import RouterAIAdapter


def test_non_chat_models_are_rejected():
    assert not RouterAIAdapter._is_chat_model("alibaba/happyhorse-1.0")
    assert not RouterAIAdapter._is_chat_model("openai/sora-2-pro")
    assert not RouterAIAdapter._is_chat_model("google/gemini-3.1-flash-image")
    assert RouterAIAdapter._is_chat_model("openai/gpt-oss-20b")


def test_ordered_models_free_first_without_network(monkeypatch):
    adapter = RouterAIAdapter("test-key")
    models = ["vendor/paid-chat", "vendor/free-chat"]

    monkeypatch.setattr(adapter, "models", lambda force=False: models)
    monkeypatch.setattr(adapter, "free_models", lambda candidates=None, force=False: ["vendor/free-chat"])

    assert adapter.ordered_models(allow_paid=True) == ["vendor/free-chat", "vendor/paid-chat"]
    assert adapter.ordered_models(allow_paid=False) == ["vendor/free-chat"]


def test_analyze_records_paid_fallback(monkeypatch):
    adapter = RouterAIAdapter("test-key")
    calls = []

    monkeypatch.setattr(adapter, "models", lambda force=False: ["vendor/free-chat", "vendor/paid-chat"])
    monkeypatch.setattr(adapter, "free_models", lambda candidates=None, force=False: ["vendor/free-chat"])

    def fake_request(method, url, payload=None):
        calls.append(payload["model"])
        if payload["model"] == "vendor/free-chat":
            raise RuntimeError("free model unavailable")
        return {"choices": [{"message": {"content": "OK"}}]}

    monkeypatch.setattr(adapter, "_request", fake_request)

    assert adapter.analyze("vendor/free-chat", "test", allow_paid=True) == "OK"
    assert calls == ["vendor/free-chat", "vendor/paid-chat"]
    assert adapter.last_model == "vendor/paid-chat"
    assert adapter.last_paid is True


def test_paid_fallback_can_be_disabled(monkeypatch):
    adapter = RouterAIAdapter("test-key")
    monkeypatch.setattr(adapter, "models", lambda force=False: ["vendor/free-chat", "vendor/paid-chat"])
    monkeypatch.setattr(adapter, "free_models", lambda candidates=None, force=False: ["vendor/free-chat"])

    def fail_request(method, url, payload=None):
        raise RuntimeError("free model unavailable")

    monkeypatch.setattr(adapter, "_request", fail_request)

    assert adapter.analyze("vendor/free-chat", "test", allow_paid=False) is None
    assert adapter.last_paid is False
