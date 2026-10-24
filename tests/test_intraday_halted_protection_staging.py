"""Static fail-safe checks for opt-in protection while entries are halted."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HaltedProtectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "intraday_executor.py").read_text()
        cls.tree = ast.parse(cls.source)

    def test_default_off(self):
        self.assertIn('os.environ.get("INTRADAY_PROTECT_WHILE_HALTED", "OFF")', self.source)

    def test_requires_protection_only(self):
        self.assertIn('protection_only\n        and os.environ.get(', self.source)

    def test_kill_switch_halts_unless_explicit_override(self):
        self.assertIn('if kill_switch_off() and not allow_protection_while_halted:', self.source)

    def test_only_closes_survive_protection_only(self):
        self.assertIn('trades = [t for t in trades if t.get("action") == "close"]', self.source)

    def test_syntax(self):
        self.assertTrue(self.tree.body)


if __name__ == "__main__":
    unittest.main()
