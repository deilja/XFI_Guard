import unittest

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

    def test_ordered_models_has_no_model_cap(self):
        adapter = RouterAIAdapter(api_key="test")
        models = [f"model/{i}" for i in range(64)]
        free = models[:32]
        adapter.free_models = lambda candidates=None, force=False: free
        result = adapter.ordered_models(models, allow_paid=True)
        self.assertEqual(len(result), 64)
        self.assertEqual(result[:32], free)
        self.assertEqual(result[32:], models[32:])

    def test_analyze_tries_free_before_paid(self):
        adapter = RouterAIAdapter(api_key="test")
        calls = []
        adapter.ordered_models = lambda candidates=None, allow_paid=True, preferred=None: ["free/model", "paid/model"]
        adapter.free_models = lambda candidates=None, force=False: ["free/model"]

        def fake_request(method, url, payload=None):
            calls.append(payload["model"])
            if payload["model"] == "free/model":
                return {"choices": [{}]}
            return {"choices": [{"message": {"content": "OK"}}]}

        adapter._request = fake_request
        self.assertEqual(adapter.analyze("paid/model", "test"), "OK")
        self.assertEqual(calls, ["free/model", "paid/model"])


if __name__ == "__main__":
    unittest.main()
