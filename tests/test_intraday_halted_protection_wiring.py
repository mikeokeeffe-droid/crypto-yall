"""Regression checks for halted Intraday protection wiring (no network/orders).

These static checks guard key fail-closed invariants. They are not a substitute
for mocked execution tests or a controlled testnet trial.
"""
import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class HaltedProtectionWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.executor = (ROOT / "intraday_executor.py").read_text()
        cls.wrapper = (ROOT / "intraday_profit_protection.py").read_text()
        cls.workflow = (ROOT / ".github/workflows/execute-intraday.yml").read_text()
        ast.parse(cls.executor)
        ast.parse(cls.wrapper)

    def test_opt_in_required_for_halted_protection(self):
        self.assertIn('protection_only\n        and os.environ.get("INTRADAY_PROTECT_WHILE_HALTED", "OFF").upper() == "ON"', self.executor)
        self.assertIn('if kill_switch_off() and not allow_protection_while_halted:', self.executor)
        self.assertIn('sys.exit(0)', self.executor)

    def test_protection_only_cannot_submit_entry(self):
        self.assertIn('trades = [t for t in trades if t.get("action") == "close"]', self.executor)
        self.assertIn('trades = [] if PROTECTION_ONLY else _original_decide_trades(', self.wrapper)

    def test_only_owned_positions_are_managed(self):
        self.assertIn('if c in owned_coins', self.executor)
        self.assertIn('managed_positions = {', self.executor)

    def test_missing_ticker_does_not_force_close(self):
        self.assertIn('profit protection skipped {coin}: ticker unavailable', self.wrapper)

    def test_workflow_monitor_has_explicit_halt_opt_in(self):
        self.assertIn("vars.INTRADAY_PROTECT_WHILE_HALTED == 'ON'", self.workflow)
        self.assertIn("INTRADAY_PROTECTION_ONLY: 'ON'", self.workflow)


if __name__ == "__main__":
    unittest.main()
