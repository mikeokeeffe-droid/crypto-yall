"""Network-free documented /info -> signer-free fixture compatibility tests."""
import copy
import unittest

from offline_documented_info_projection_ci import (
    project_offline_documented_info_snapshot,
)
from offline_signer_free_info_fixture_ci import (
    OfflineSignerFreeInfoScope, make_signer_free_info_fixture,
)

ACCOUNT = "0x" + "1" * 40
SCOPE = OfflineSignerFreeInfoScope("testnet", ACCOUNT)


def responses():
    return {
        "clearinghouse_state": {
            "marginSummary": {
                "accountValue": "120.50", "totalMarginUsed": "50",
                "totalRawUsd": "120.50", "totalNtlPos": "100",
            },
            "assetPositions": [{
                "type": "oneWay",
                "position": {
                    "coin": "SOL", "szi": "-0.25", "entryPx": "100",
                    "unrealizedPnl": "-1.50",
                    "leverage": {"type": "isolated", "value": 2,
                                 "rawUsd": "-25.0"},
                    "cumFunding": {"allTime": "0.1", "sinceOpen": "0.1"},
                    "liquidationPx": "150", "positionValue": "25",
                },
            }],
            "crossMarginSummary": {"accountValue": "120.50"},
            "withdrawable": "40",
        },
        "spot_state": {
            "balances": [
                {"coin": "USDC", "total": "22.4", "hold": "2.1",
                 "entryNtl": "15", "token": 0},
            ],
        },
        "all_mids": {"SOL": "104.10", "AVAX": "25", "@12": "1.0"},
        "meta": {
            "universe": [
                {"name": "SOL", "szDecimals": 3, "maxLeverage": 20},
                {"name": "AVAX", "szDecimals": 2, "maxLeverage": 10},
            ],
            "marginTables": [{"description": "synthetic"}],
        },
    }


def project(data, scope=SCOPE):
    return project_offline_documented_info_snapshot(scope=scope, **data)


class DocumentedInfoProjectionTests(unittest.TestCase):
    def test_extra_real_world_fields_are_discarded_without_trading_authority(self):
        normalized = project(responses())
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["user_state"]["marginSummary"],
                         {"accountValue": "120.50"})
        self.assertEqual(normalized["user_state"]["assetPositions"], [{
            "position": {
                "coin": "SOL", "szi": "-0.25", "entryPx": "100",
                "unrealizedPnl": "-1.50", "leverage": "2",
            },
        }])
        self.assertEqual(normalized["spot_state"],
                         {"balances": [{"coin": "USDC", "total": "22.4"}]})
        self.assertEqual(normalized["all_mids"],
                         {"SOL": "104.10", "AVAX": "25"})
        self.assertEqual(normalized["meta"],
                         {"universe": [{"name": "SOL", "szDecimals": 3},
                                       {"name": "AVAX", "szDecimals": 2}]})
        self.assertNotIn("withdrawable", str(normalized))
        self.assertNotIn("liquidationPx", str(normalized))
        view = make_signer_free_info_fixture(scope=SCOPE, snapshot=normalized)
        self.assertIsNotNone(view)
        self.assertFalse(view.origin_authenticated)
        self.assertFalse(view.ownership_verified)
        self.assertFalse(view.submit_authorized)
        self.assertFalse(hasattr(view, "market_open"))
        with self.assertRaises(PermissionError):
            view.user_fills(ACCOUNT)

    def test_wrong_scope_missing_critical_values_and_duplicates_hold(self):
        self.assertIsNone(project(responses(),
                                  OfflineSignerFreeInfoScope("mainnet", ACCOUNT)))
        cases = []
        d = responses()
        d["clearinghouse_state"]["marginSummary"]["accountValue"] = "NaN"
        cases.append(d)
        d = responses()
        d["clearinghouse_state"]["assetPositions"][0]["position"]["coin"] = "BTC"
        cases.append(d)
        d = responses()
        d["clearinghouse_state"]["assetPositions"].append(
            copy.deepcopy(d["clearinghouse_state"]["assetPositions"][0]))
        cases.append(d)
        d = responses()
        d["clearinghouse_state"]["assetPositions"][0]["position"]["leverage"]["value"] = -1
        cases.append(d)
        d = responses()
        d["spot_state"]["balances"][0]["total"] = "-3"
        cases.append(d)
        d = responses()
        d["all_mids"]["SOL"] = "Infinity"
        cases.append(d)
        d = responses()
        d["meta"]["universe"].append(copy.deepcopy(d["meta"]["universe"][0]))
        cases.append(d)
        d = responses()
        d["clearinghouse_state"]["assetPositions"][0]["position"]["szi"] = True
        cases.append(d)
        for data in cases:
            with self.subTest(data=str(data)[:100]):
                self.assertIsNone(project(data))

    def test_no_live_sdk_or_original_executors_loaded(self):
        import sys
        self.assertNotIn("hyperliquid.exchange", sys.modules)
        self.assertNotIn("hyperliquid_executor", sys.modules)
        self.assertNotIn("intraday_executor", sys.modules)
        self.assertNotIn("aggressive_executor", sys.modules)


if __name__ == "__main__":
    unittest.main()
