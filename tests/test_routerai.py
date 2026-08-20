import unittest
from unittest.mock import patch

from xfi_guard.routerai import RouterAIAdapter


class RouterAITests(unittest.TestCase):
    def test_free_chat_endpoint_filter(self):
        base = {
            "status": 0,
            "pricing": {"prompt": 0, "completion": 0},
            "supported_apis": ["chat"],
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        }
        self.assertTrue(RouterAIAdapter._is_free_chat_endpoint(base))

        image = {**base, "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]}}
        self.assertFalse(RouterAIAdapter._is_free_chat_endpoint(image))

        messages_only = {**base, "supported_apis": ["messages"]}
        self.assertFalse(RouterAIAdapter._is_free_chat_endpoint(messages_only))

        paid = {**base, "pricing": {"prompt": 0.001, "completion": 0}}
        self.assertFalse(RouterAIAdapter._is_free_chat_endpoint(paid))
        self.assertTrue(RouterAIAdapter._is_paid_chat_endpoint(paid))

    def test_content_parser_openai_text(self):
        result = {"choices": [{"message": {"content": "  OK  "}}]}
        self.assertEqual(RouterAIAdapter._content_from_response(result), "OK")

    def test_content_parser_content_parts(self):
        result = {
            "choices": [{
                "message": {
                    "content": [
                        {"type": "text", "text": "risk=low"},
                        {"type": "text", "text": " confidence=0.9"},
                    ]
                }
            }]
        }
        self.assertEqual(RouterAIAdapter._content_from_response(result), "risk=low\n confidence=0.9")

    def test_content_parser_reasoning_fallback(self):
        result = {"choices": [{"message": {"content": None, "reasoning_content": "OK"}}]}
        self.assertEqual(RouterAIAdapter._content_from_response(result), "OK")

    def test_content_parser_empty(self):
        self.assertIsNone(RouterAIAdapter._content_from_response({"choices": []}))
        self.assertIsNone(RouterAIAdapter._content_from_response({}))

    def test_free_models_do_not_enable_paid_fallback(self):
        adapter = RouterAIAdapter("test-key")
        endpoints = {
            "free/model": {"data": {"endpoints": [{
                "status": 0,
                "pricing": {"prompt": 0, "completion": 0},
                "supported_apis": ["chat"],
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            }]}},
            "paid/model": {"data": {"endpoints": [{
                "status": 0,
                "pricing": {"prompt": 0.001, "completion": 0.002},
                "supported_apis": ["chat"],
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            }]}},
        }

        def fake_request(method, url, payload=None):
            model = url.rsplit("/models/", 1)[-1].replace("/endpoints", "")
            return endpoints[model]

        with patch.object(adapter, "_raw_models", return_value=["free/model", "paid/model"]), \
             patch.object(adapter, "_request", side_effect=fake_request):
            self.assertEqual(adapter.free_models(), ["free/model"])
            self.assertEqual(adapter.text_models(include_paid=False), ["free/model"])

    def test_models_are_free_first(self):
        adapter = RouterAIAdapter("test-key")
        endpoint_map = {
            "free/model": {"data": {"endpoints": [{
                "status": 0, "pricing": {"prompt": 0, "completion": 0},
                "supported_apis": ["chat"], "architecture": {"output_modalities": ["text"]},
            }]}},
            "paid/model": {"data": {"endpoints": [{
                "status": 0, "pricing": {"prompt": 0.001, "completion": 0.002},
                "supported_apis": ["chat"], "architecture": {"output_modalities": ["text"]},
            }]}},
        }

        def fake_request(method, url, payload=None):
            model = url.rsplit("/models/", 1)[-1].replace("/endpoints", "")
            return endpoint_map[model]

        with patch.object(adapter, "_raw_models", return_value=["paid/model", "free/model"]), \
             patch.object(adapter, "_request", side_effect=fake_request):
            self.assertEqual(adapter.models(), ["free/model", "paid/model"])

    def test_analyze_uses_free_before_paid(self):
        adapter = RouterAIAdapter("test-key")
        adapter._set_classification(["free/model"], ["paid/model"])
        calls = []

        def fake_request(method, url, payload=None):
            calls.append(payload["model"])
            if payload["model"] == "free/model":
                raise RuntimeError("free endpoint unavailable")
            return {"choices": [{"message": {"content": "OK"}}]}

        with patch.object(adapter, "_request", side_effect=fake_request):
            self.assertEqual(adapter.analyze("free/model", "test"), "OK")
        self.assertEqual(calls, ["free/model", "paid/model"])


if __name__ == "__main__":
    unittest.main()
