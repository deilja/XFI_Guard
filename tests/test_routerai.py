import json
from unittest.mock import patch

from xfi_guard.routerai import RouterAIAdapter


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_free_models_are_detected_from_zero_pricing():
    adapter = RouterAIAdapter("test-key")

    def fake_request(method, url, payload=None):
        if url.endswith("/models"):
            return {"data": [{"id": "provider/free-chat"}, {"id": "provider/paid-chat"}]}
        if url.endswith("/provider/free-chat/endpoints"):
            return {"data": {"endpoints": [{"pricing": {"prompt": "0", "completion": "0"}, "status": 200}]}}
        if url.endswith("/provider/paid-chat/endpoints"):
            return {"data": {"endpoints": [{"pricing": {"prompt": "0.001", "completion": "0.002"}, "status": 200}]}}
        raise AssertionError(url)

    with patch.object(adapter, "_request", side_effect=fake_request):
        assert adapter.free_models(force=True) == ["provider/free-chat"]


def test_ordered_models_never_puts_paid_preferred_before_free():
    adapter = RouterAIAdapter("test-key")
    with patch.object(adapter, "models", return_value=["provider/free-chat", "provider/paid-chat"]), \
         patch.object(adapter, "free_models", return_value=["provider/free-chat"]):
        assert adapter.ordered_models(preferred="provider/paid-chat", allow_paid=True) == [
            "provider/free-chat", "provider/paid-chat"
        ]
        assert adapter.ordered_models(preferred="provider/paid-chat", allow_paid=False) == [
            "provider/free-chat"
        ]


def test_analyze_uses_free_model_first_and_records_model():
    adapter = RouterAIAdapter("test-key")
    with patch.object(adapter, "ordered_models", return_value=["provider/free-chat", "provider/paid-chat"]), \
         patch.object(adapter, "_request", return_value={"choices": [{"message": {"content": "OK"}}]}):
        result = adapter.analyze("provider/paid-chat", "Reply OK", allow_paid=True)

    assert result == "OK"
    assert adapter.last_model == "provider/free-chat"
    assert adapter.last_error == ""
