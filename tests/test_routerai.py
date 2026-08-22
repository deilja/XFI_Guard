from xfi_guard.routerai import RouterAIAdapter


def test_zero_accepts_numeric_string_and_free_labels():
    assert RouterAIAdapter._zero("0")
    assert RouterAIAdapter._zero("0.000000")
    assert RouterAIAdapter._zero("free")
    assert RouterAIAdapter._zero({"value": "0"})
    assert not RouterAIAdapter._zero("0.001")


def test_pricing_free_detection():
    assert RouterAIAdapter._pricing_is_free({"prompt": "0", "completion": "0"})
    assert RouterAIAdapter._pricing_is_free({"free": True})
    assert not RouterAIAdapter._pricing_is_free({"prompt": "0", "completion": "0.01"})


def test_model_free_detection_supports_common_flags():
    assert RouterAIAdapter._model_is_free({"free": True})
    assert RouterAIAdapter._model_is_free({"pricing": {"prompt": 0, "completion": 0}})
    assert not RouterAIAdapter._model_is_free({"pricing": {"prompt": 0, "completion": 1}})


def test_endpoint_items_supports_nested_shapes():
    data = {"data": {"endpoints": [{"pricing": {"prompt": "0", "completion": "0"}}]}}
    assert len(RouterAIAdapter._endpoint_items(data)) == 1


def test_ordered_models_puts_free_before_paid(monkeypatch):
    adapter = RouterAIAdapter("test-key")
    monkeypatch.setattr(adapter, "models", lambda force=False: ["paid/model", "free/model"])
    monkeypatch.setattr(adapter, "free_models", lambda candidates=None, force=False: ["free/model"])

    assert adapter.ordered_models(allow_paid=True) == ["free/model", "paid/model"]
    assert adapter.ordered_models(allow_paid=False) == ["free/model"]


def test_ordered_models_prefers_requested_free_model(monkeypatch):
    adapter = RouterAIAdapter("test-key")
    monkeypatch.setattr(adapter, "models", lambda force=False: ["free/a", "free/b", "paid/c"])
    monkeypatch.setattr(adapter, "free_models", lambda candidates=None, force=False: ["free/a", "free/b"])

    assert adapter.ordered_models(preferred="free/b") == ["free/b", "free/a", "paid/c"]
