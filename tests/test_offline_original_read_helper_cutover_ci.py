"""Real legacy read-helper bodies, isolated from signer imports and trading.

No execution of the original executor module. The source-extracted helpers run
only against immutable-copy synthetic Info. This checks compatibility, not
exchange authenticity or a safe deployment boundary.
"""
from pathlib import Path
import sys
import tempfile
import unittest

from offline_original_read_helper_cutover_ci import (
    extract_original_info_read_helpers_offline,
)
from offline_signer_free_read_bootstrap_ci import (
    bootstrap_original_read_only_offline,
)

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "0x" + "1" * 40


def fixture(*, account_value="150", spot_balance="40", leverage=None):
    return {
        "environment": "testnet", "account": ACCOUNT,
        "user_state": {
            "marginSummary": {"accountValue": account_value},
            "assetPositions": [
                {"position": {
                    "coin": "SOL", "szi": "0.50", "entryPx": "100",
                    "unrealizedPnl": "12", "leverage": (
                        leverage if leverage is not None
                        else {"type": "cross", "value": 2}
                    ),
                }},
                {"position": {
                    "coin": "AVAX", "szi": "-1.25", "entryPx": "35",
                    "unrealizedPnl": "-2", "leverage": "3",
                }},
            ],
        },
        "spot_state": {
            "balances": [{"coin": "USDC", "total": spot_balance}],
        },
        "all_mids": {"SOL": "125", "AVAX": "32"},
        "meta": {"universe": [
            {"name": "SOL", "szDecimals": 3},
            {"name": "AVAX", "szDecimals": 2},
        ]},
    }


def view(bot="daily", **updates):
    result = bootstrap_original_read_only_offline(
        verified_bot=bot, pinned_environment="testnet",
        pinned_account=ACCOUNT, snapshot=fixture(**updates),
    )
    if result is None:
        raise AssertionError("synthetic signer-free bootstrap missing")
    return result


class OriginalReadHelperCutoverTests(unittest.TestCase):
    def test_all_three_bot_read_surfaces_match_original_legacy_functions(self):
        helpers = extract_original_info_read_helpers_offline(source_root=ROOT)
        self.assertEqual(set(helpers), {
            "get_account_equity", "get_open_positions", "get_mid_price",
            "coin_is_listed", "get_size_decimals",
        })
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                v = view(bot)
                self.assertFalse(v.origin_authenticated)
                self.assertFalse(v.ownership_verified)
                self.assertFalse(v.submit_authorized)
                self.assertEqual(helpers["get_account_equity"](v.info, ACCOUNT), 150.0)
                self.assertEqual(
                    helpers["get_open_positions"](v.info, ACCOUNT), {
                        "SOL": {
                            "size": 0.5, "entry_px": 100.0,
                            "unrealized_pnl": 12.0, "leverage": 2.0,
                        },
                        "AVAX": {
                            "size": -1.25, "entry_px": 35.0,
                            "unrealized_pnl": -2.0, "leverage": 3.0,
                        },
                    },
                )
                self.assertEqual(helpers["get_mid_price"](v.info, "SOL"), 125.0)
                self.assertTrue(helpers["coin_is_listed"](v.info, "SOL"))
                self.assertFalse(helpers["coin_is_listed"](v.info, "BTC"))
                self.assertEqual(helpers["get_size_decimals"](v.info, "SOL"), 3)
                self.assertEqual(helpers["get_size_decimals"](v.info, "UNKNOWN"), 3)

    def test_legacy_equity_fallback_and_leverage_parsing(self):
        helpers = extract_original_info_read_helpers_offline(source_root=ROOT)
        v = view("daily", account_value="5", spot_balance="40",
                 leverage={"type": "isolated", "value": 4})
        self.assertEqual(helpers["get_account_equity"](v.info, ACCOUNT), 40.0)
        self.assertEqual(
            helpers["get_open_positions"](v.info, ACCOUNT)["SOL"]["leverage"],
            4.0,
        )

    def test_wrong_account_not_readable(self):
        helpers = extract_original_info_read_helpers_offline(source_root=ROOT)
        with self.assertRaises(PermissionError):
            helpers["get_open_positions"](view().info, "0x" + "2" * 40)

    def test_tampered_helper_calls_and_imports_rejected_before_running(self):
        original = (ROOT / "hyperliquid_executor.py").read_text("utf-8")
        cases = (
            original.replace(
                "return float(info.all_mids()[coin])",
                "return info.market_open('SOL', True, 1)",
                1,
            ),
            original.replace(
                "return float(info.all_mids()[coin])",
                "import os\n    return os.getenv('HL_PRIVATE_KEY')",
                1,
            ),
            original.replace(
                "return float(info.all_mids()[coin])",
                "return __import__('os').environ",
                1,
            ),
        )
        for mutated in cases:
            with self.subTest(length=len(mutated)):
                with tempfile.TemporaryDirectory() as directory:
                    (Path(directory) / "hyperliquid_executor.py").write_text(
                        mutated, encoding="utf-8",
                    )
                    with self.assertRaises(ValueError):
                        extract_original_info_read_helpers_offline(
                            source_root=Path(directory),
                        )

    def test_no_legacy_or_signer_import(self):
        extract_original_info_read_helpers_offline(source_root=ROOT)
        for module in ("hyperliquid_executor", "intraday_executor",
                       "aggressive_executor", "eth_account",
                       "hyperliquid.exchange"):
            self.assertNotIn(module, sys.modules)


if __name__ == "__main__":
    unittest.main()
