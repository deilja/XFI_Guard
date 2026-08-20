import unittest

from xfi_guard.ai import AIAnalyzer
from xfi_guard.routerai import RouterAIAdapter


class RouterAIFallbackTests(unittest.TestCase):
    def test_ordered_models_put_free_first(self):
        adapter = RouterAIAdapter(api_key="test")
        adapter.free_models = lambda candidates=None, force=False: ["free/model"]
        result = adapter.ordered_models(["paid/model", "free/model"], allow_paid=True)
        self.assertEqual(result, ["free/model", "paid/model"])

    def test_ordered_models_can_disable_paid(self):
        adapter = RouterAIAdapter(api_key="test")
        adapter.free_models = lambda candidates=None, force=False: ["free/model"]
        result = adapter.ordered_models(["paid/model", "free/model"], allow_paid=False)
        self.assertEqual(result, ["free/model"])

    def test_analyze_tries_free_before_paid(self):
        adapter = RouterAIAdapter(api_key="test")
        calls = []
        adapter.ordered_models = lambda candidates=None, allow_paid=True, preferred=None: [
            "free/model",
            "paid/model",
        ]

        def fake_request(method, url, payload=None):
            calls.append(payload["model"])
            if payload["model"] == "free/model":
                return {"choices": [{}]}
            return {"choices": [{"message": {"content": "OK"}}]}

        adapter._request = fake_request
        self.assertEqual(adapter.analyze("paid/model", "test"), "OK")
        self.assertEqual(calls, ["free/model", "paid/model"])
        self.assertEqual(adapter.last_model, "paid/model")
        self.assertEqual(adapter.last_error, "")

    def test_analyze_does_not_request_paid_when_disabled(self):
        adapter = RouterAIAdapter(api_key="test")
        calls = []
        adapter.ordered_models = lambda candidates=None, allow_paid=False, preferred=None: ["free/model"]

        def fake_request(method, url, payload=None):
            calls.append(payload["model"])
            return {"choices": [{"message": {"content": "OK"}}]}

        adapter._request = fake_request
        self.assertEqual(adapter.analyze("paid/model", "test", allow_paid=False), "OK")
        self.assertEqual(calls, ["free/model"])

    def test_ai_analyzer_exposes_direct_analyze(self):
        analyzer = AIAnalyzer()
        self.assertTrue(callable(getattr(analyzer, "analyze", None)))


if __name__ == "__main__":
    unittest.main()
