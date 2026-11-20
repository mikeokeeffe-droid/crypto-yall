"""Static, no-network isolation regression checks."""
import unittest
from pathlib import Path
from offline_hyperliquid_isolation_guard import (
    inspect_offline_source_isolation, inspect_offline_module_files,
)

class IsolationTests(unittest.TestCase):
    def test_actual_offline_modules_are_isolated(self):
        root = Path(__file__).resolve().parents[1]
        result = inspect_offline_module_files(root=root)
        self.assertEqual(result.status, "review_only", result.reason)

    def test_forbidden_imports_and_side_effects_hold(self):
        samples = (
            "import requests",
            "from urllib.request import urlopen",
            "import hyperliquid.exchange",
            "import supabase",
            "from intraday_executor import run",
            "import socket",
            "client.post('https://example.com')",
            "connection.connect()",
            "eval('1')",
            "import os\nos.system('echo no')",
        )
        for source in samples:
            with self.subTest(source=source):
                self.assertEqual(inspect_offline_source_isolation(
                    source=source, filename="synthetic.py").status, "hold")

    def test_malformed_source_holds(self):
        self.assertEqual(inspect_offline_source_isolation(
            source="def broken(", filename="synthetic.py").status, "hold")

if __name__ == "__main__":
    unittest.main()
