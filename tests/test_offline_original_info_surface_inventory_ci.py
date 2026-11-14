"""Source-level complete original Info method inventory, LIVE NO-GO."""
from pathlib import Path
import sys
import unittest

from offline_original_info_surface_inventory_ci import (
    FILES, REQUIRED_READS, HISTORY_READS,
    audit_original_info_read_surface_offline,
)
from offline_signer_free_read_bootstrap_ci import (
    bootstrap_original_read_only_offline,
)

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "0x" + "1" * 40


def actual_sources():
    return {name: (ROOT / name).read_text(encoding="utf-8")
            for name in FILES}


class OriginalInfoSurfaceInventoryTests(unittest.TestCase):
    def test_complete_original_source_reads_include_blocked_history(self):
        report = audit_original_info_read_surface_offline(actual_sources())
        self.assertEqual(report.state, "hold")
        self.assertTrue(report.source_shape_matches)
        self.assertEqual(set(report.methods), REQUIRED_READS)
        self.assertEqual(set(report.unsupported_history_reads), HISTORY_READS)
        self.assertFalse(report.signer_free_runtime_verified)
        self.assertFalse(report.account_history_complete)
        self.assertFalse(report.trading_authorized)

    def test_synthetic_info_refuses_order_fills_and_funding_history(self):
        snapshot = {
            "environment": "testnet", "account": ACCOUNT,
            "user_state": {
                "marginSummary": {"accountValue": "150"},
                "assetPositions": [],
            },
            "spot_state": {"balances": [{"coin": "USDC", "total": "40"}]},
            "all_mids": {"SOL": "125"},
            "meta": {"universe": [{"name": "SOL", "szDecimals": 3}]},
        }
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                client = bootstrap_original_read_only_offline(
                    verified_bot=bot, pinned_environment="testnet",
                    pinned_account=ACCOUNT, snapshot=snapshot,
                )
                self.assertIsNotNone(client)
                with self.assertRaises(PermissionError):
                    client.info.user_fills(ACCOUNT)
                with self.assertRaises(PermissionError):
                    client.info.user_funding_history(ACCOUNT, 1, 100)
                self.assertFalse(client.origin_authenticated)
                self.assertFalse(client.ownership_verified)
                self.assertFalse(client.submit_authorized)

    def test_unknown_new_info_method_fails_source_contract(self):
        sources = actual_sources()
        for method in ("user_orders", "spot_user_state_new", "order_status"):
            mutated = dict(sources)
            mutated["hyperliquid_executor.py"] += (
                "\ndef injected_read(info):\n    return info."
                + method + "('some value')\n"
            )
            report = audit_original_info_read_surface_offline(mutated)
            self.assertFalse(report.source_shape_matches)
            self.assertFalse(report.trading_authorized)
            self.assertIn("unreviewed original Info method", report.reason)

    def test_dropped_history_read_and_forged_adapter_both_hold(self):
        sources = actual_sources()
        replaced = dict(sources)
        before = replaced["hyperliquid_executor.py"]
        replaced["hyperliquid_executor.py"] = before.replace(
            "info.user_fills(address)", "[]", 1,
        )
        self.assertNotEqual(replaced["hyperliquid_executor.py"], before)
        report = audit_original_info_read_surface_offline(replaced)
        self.assertFalse(report.source_shape_matches)
        self.assertFalse(report.trading_authorized)
        self.assertFalse(
            audit_original_info_read_surface_offline(
                sources, history_adapter=object(),
            ).source_shape_matches
        )

    def test_no_signer_or_original_executor_imports(self):
        report = audit_original_info_read_surface_offline(actual_sources())
        self.assertEqual(report.state, "hold")
        for name in ("hyperliquid_executor", "intraday_executor",
                     "aggressive_executor", "eth_account",
                     "hyperliquid.exchange"):
            self.assertNotIn(name, sys.modules)


if __name__ == "__main__":
    unittest.main()
