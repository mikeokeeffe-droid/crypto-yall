"""No-network, no-key account view compatibility tests for strategy migration."""
import ast
from pathlib import Path
import unittest

from sender_review.signer_free_account_view_offline import (
    extract_signer_free_account_view_offline,
)


def account(*positions, equity="100"):
    return {"marginSummary": {"accountValue": equity},
            "assetPositions": [{"position": p} for p in positions]}


def position(*, coin="SOL", size="0.25", price="100",
             pnl="1.25", leverage=2):
    return {"coin": coin, "szi": size, "entryPx": price,
            "unrealizedPnl": pnl, "leverage": {"type": "cross",
                                            "value": leverage}}


class SignerFreeAccountViewOfflineTests(unittest.TestCase):
    def assert_no_authority(self, result):
        for flag in (
            "exchange_origin_authenticated", "account_scope_verified",
            "position_ownership_verified", "historic_baseline_verified",
            "snapshot_freshness_verified", "signer_available",
            "order_authorized", "close_authorized", "leverage_authorized",
        ):
            self.assertIs(getattr(result, flag), False, flag)

    def test_original_data_shape_long_short_and_flat(self):
        sample = account(
            position(coin="SOL", size="0.25", pnl="1.25", leverage=2),
            position(coin="AVAX", size="-0.50", price="20", pnl="-2", leverage=3),
            position(coin="LINK", size="0", leverage=1), equity="501.50",
        )
        view = extract_signer_free_account_view_offline(user_state=sample)
        self.assertEqual(view.state, "PARSED_READONLY_FIXTURE_HOLD")
        self.assertTrue(view.fixture_parsed)
        self.assertEqual(view.equity, 501.5)
        self.assertEqual(view.positions, {
            "SOL": {"size": 0.25, "entry_px": 100.0,
                    "unrealized_pnl": 1.25, "leverage": 2.0},
            "AVAX": {"size": -0.5, "entry_px": 20.0,
                     "unrealized_pnl": -2.0, "leverage": 3.0},
        })
        self.assert_no_authority(view)

    def test_spot_fallback_is_visible_additional_read_dependency(self):
        sample = account(position(), equity="5")
        absent = extract_signer_free_account_view_offline(user_state=sample)
        self.assertEqual(absent.state, "HOLD")
        self.assertTrue(absent.additional_spot_read_needed)
        self.assertFalse(absent.fixture_parsed)
        self.assert_no_authority(absent)
        with_spot = extract_signer_free_account_view_offline(
            user_state=sample, spot_user_state={
                "balances": [{"coin": "BTC", "total": "1"},
                             {"coin": "USDC", "total": "22.75"}],
            })
        self.assertEqual(with_spot.equity, 22.75)
        self.assertTrue(with_spot.legacy_spot_fallback_used)
        self.assertTrue(with_spot.fixture_parsed)
        self.assert_no_authority(with_spot)
        no_usdc = extract_signer_free_account_view_offline(
            user_state=sample, spot_user_state={"balances": []})
        self.assertEqual(no_usdc.equity, 5.0)
        self.assertFalse(no_usdc.legacy_spot_fallback_used)
        self.assert_no_authority(no_usdc)

    def test_untrusted_stale_ambiguous_or_invalid_values_hold(self):
        cases = [
            None, {}, account(equity="NaN"), account(equity="Infinity"),
            account(equity="-1"), account(position(size="NaN")),
            account(position(size="1e1000")), account(position(price="-5")),
            account(position(pnl="Infinity")), account(position(leverage=-1)),
            account(position(leverage="NaN")), account(position(coin="../SOL")),
            account(position(), position()), account(position(coin="sol")),
            account(equity="1e1000"),
            account(position(size="1000001")),
            account(position(leverage=[])),
            account(position(leverage=False)),
            account(position(leverage=True)),
            account(position(leverage={"value": False})),
            account(position(leverage={"value": True})),
        ]
        for sample in cases:
            with self.subTest(sample=str(sample)[:100]):
                view = extract_signer_free_account_view_offline(user_state=sample)
                self.assertEqual(view.state, "HOLD")
                self.assertFalse(view.fixture_parsed)
                self.assert_no_authority(view)
        for spot in ({"balances": [{"coin": "USDC", "total": "NaN"}]},
                     {"balances": [{"coin": "USDC", "total": "1"},
                                   {"coin": "USDC", "total": "2"}]},
                     {"balances": None}):
            with self.subTest(spot=str(spot)):
                result = extract_signer_free_account_view_offline(
                    user_state=account(equity="5"), spot_user_state=spot)
                self.assertEqual(result.state, "HOLD")
                self.assert_no_authority(result)

    def test_import_graph_has_no_signer_exchange_network_or_client(self):
        module = Path(__file__).with_name("signer_free_account_view_offline.py")
        seen = set()
        for node in ast.walk(ast.parse(module.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                seen.update(a.name for a in node.names)
            if isinstance(node, ast.ImportFrom):
                seen.add(node.module)
        self.assertEqual(seen, {"dataclasses", "math", "re"})


if __name__ == "__main__":
    unittest.main()
