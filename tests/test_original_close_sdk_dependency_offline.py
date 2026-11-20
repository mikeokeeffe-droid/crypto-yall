"""Offline SDK dependency contract for original bot close orders.

This does not inspect the installed SDK implementation or authorize trades.
A passing test only records the version that requires independent review.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CloseSdkDependencyTests(unittest.TestCase):
    def test_hyperliquid_sdk_version_is_pinned_for_close_review(self):
        lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        pins = [line.strip() for line in lines
                if line.strip().startswith("hyperliquid-python-sdk")]
        self.assertEqual(pins, ["hyperliquid-python-sdk==0.24.0"],
                         "SDK version changed; re-audit market_close reduce-only behavior")

    def test_all_three_originals_use_sdk_market_close(self):
        for name in ("aggressive_executor.py", "intraday_executor.py",
                     "hyperliquid_executor.py"):
            with self.subTest(name=name):
                source = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("exchange.market_close(coin", source)

if __name__ == "__main__":
    unittest.main()
