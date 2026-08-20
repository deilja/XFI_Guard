import unittest

from xfi_guard.routerai import RouterAIAdapter


class RouterAITests(unittest.TestCase):
    def test_free_chat_endpoint_filter(self):
        base = {
            "status": 0,
            "pricing": {"prompt": 0, "completion": 0},
            "supported_apis": ["chat"],
            "architecture": {"output_modalities": ["text"]},
        }
        self.assertTrue(RouterAIAdapter._is_free_chat_endpoint(base))

        image = {
            **base,
            "architecture": {"output_modalities": ["image"]},
        }
        self.assertFalse(RouterAIAdapter._is_free_chat_endpoint(image))

        messages_only = {
            **base,
            "supported_apis": ["messages"],
        }
        self.assertFalse(RouterAIAdapter._is_free_chat_endpoint(messages_only))

        paid = {
            **base,
            "pricing": {"prompt": 0.001, "completion": 0},
        }
        self.assertFalse(RouterAIAdapter._is_free_chat_endpoint(paid))

    def test_content_parser_openai_text(self):
        result = {
            "choices": [{"message": {"content": "  OK  "}}],
        }
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
        self.assertEqual(
            RouterAIAdapter._content_from_response(result),
            "risk=low\n confidence=0.9",
        )

    def test_content_parser_reasoning_fallback(self):
        result = {
            "choices": [{"message": {"content": None, "reasoning_content": "OK"}}],
        }
        self.assertEqual(RouterAIAdapter._content_from_response(result), "OK")

    def test_content_parser_empty(self):
        self.assertIsNone(RouterAIAdapter._content_from_response({"choices": []}))
        self.assertIsNone(RouterAIAdapter._content_from_response({}))


if __name__ == "__main__":
    unittest.main()
