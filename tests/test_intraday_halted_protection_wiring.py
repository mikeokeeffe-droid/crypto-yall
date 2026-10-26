"""Staging isolation regression: production halt behaviour remains unchanged."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class HaltedProtectionIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.executor = (ROOT / "intraday_executor.py").read_text()
        cls.workflow = (ROOT / ".github/workflows/execute-intraday.yml").read_text()
        ast.parse(cls.executor)

    def test_kill_switch_still_halts(self):
        self.assertIn("if kill_switch_off():", self.executor)
        self.assertIn("sys.exit(0)", self.executor)

    def test_no_staging_override_in_production(self):
        self.assertNotIn("INTRADAY_PROTECT_WHILE_HALTED", self.executor)
        self.assertNotIn("INTRADAY_PROTECT_WHILE_HALTED", self.workflow)

    def test_close_only_path_remains(self):
        self.assertIn("PROTECTION-ONLY mode", self.executor)
        self.assertIn("if c in owned_coins", self.executor)

if __name__ == "__main__":
    unittest.main()
