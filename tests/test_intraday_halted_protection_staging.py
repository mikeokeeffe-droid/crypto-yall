"""Staging isolation: halted protection override is not deployed."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class HaltedProtectionStagingIsolationTests(unittest.TestCase):
    def test_executor_is_not_wired_to_override(self):
        source = (ROOT / "intraday_executor.py").read_text()
        ast.parse(source)
        self.assertNotIn("INTRADAY_PROTECT_WHILE_HALTED", source)
        self.assertIn("if kill_switch_off():", source)

    def test_workflow_has_no_halt_override(self):
        workflow = (ROOT / ".github/workflows/execute-intraday.yml").read_text()
        self.assertNotIn("INTRADAY_PROTECT_WHILE_HALTED", workflow)

if __name__ == "__main__":
    unittest.main()
