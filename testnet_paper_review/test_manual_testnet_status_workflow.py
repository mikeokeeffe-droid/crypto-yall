"""Offline contract checks for a manual, no-secret Testnet diagnostic workflow."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hyperliquid-testnet-public-account-status.yml"


class ManualTestnetStatusWorkflowTests(unittest.TestCase):
    def test_dispatch_only_read_only(self):
        raw = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch: {}", raw)
        for trigger in ("  schedule:", "  push:", "  pull_request:"):
            self.assertNotIn(trigger, raw)
        self.assertIn("  contents: read", raw)
        self.assertIn("persist-credentials: false", raw)
        self.assertIn("testnet_daily_readonly_preflight import review_once", raw)
        self.assertIn('result["decision"].status != "HOLD"', raw)
        self.assertIn("NO ORDERS", raw)

    def test_no_credentials_or_trade_calls(self):
        raw = WORKFLOW.read_text(encoding="utf-8")
        forbidden = (
            "secrets." , "HL_PRIVATE_KEY", "HL_TESTNET_PRIVATE_KEY",
            "HL_ACCOUNT_ADDRESS", "market_open(", "market_close(",
            "execute_trade(", "bulk_orders(", "Exchange(",
            "hyperliquid_executor", "execute-trades.yml",
            "https://api.hyperliquid.xyz", "/exchange",
        )
        for item in forbidden:
            with self.subTest(item=item):
                self.assertNotIn(item, raw)

    def test_no_trading_authorization(self):
        raw = WORKFLOW.read_text(encoding="utf-8")
        for item in ("may_send", "may_sign", "permits_submission"):
            self.assertNotIn(item, raw)
        self.assertIn("HOLD: read-only status does not grant", raw)


if __name__ == "__main__":
    unittest.main()
