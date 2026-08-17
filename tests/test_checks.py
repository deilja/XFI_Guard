import tempfile
import unittest

from xfi_guard.checks import check_disk, check_memory


class CheckTests(unittest.TestCase):
    def test_disk_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = check_disk(directory)
        self.assertEqual(result.name, "disk")
        self.assertIn(result.status, {"ok", "warning"})
        self.assertIn("percent", result.details)

    def test_memory_check_shape(self) -> None:
        result = check_memory()
        self.assertEqual(result.name, "memory")
        self.assertIn(result.status, {"ok", "warning", "unknown"})


if __name__ == "__main__":
    unittest.main()
