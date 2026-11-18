"""No-network, no-key regression tests for the unwired signer-free read seam."""
import ast
import json
from pathlib import Path
import unittest

from sender_review.signer_free_readonly_client_unwired import (
    inspect_unwired_signer_free_account_view,
    inspect_unwired_market_reference_view,
)

ACCOUNT = "0x" + "1" * 40


def encoded(value):
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def perp(*, equity="100", positions=None):
    return {
        "marginSummary": {"accountValue": equity},
        "assetPositions": positions if positions is not None else [{
            "position": {
                "coin": "SOL", "szi": "-0.25", "entryPx": "100",
                "unrealizedPnl": "1.5", "leverage": {"value": 2},
            }
        }],
    }


class SignerFreeReadOnlyUnwiredTests(unittest.TestCase):
    def assert_no_authority(self, result):
        for name in (
            "exchange_origin_authenticated", "account_scope_verified",
            "snapshot_freshness_verified", "account_wide_history_verified",
            "position_ownership_verified", "trading_key_available",
            "order_authorized", "close_authorized", "leverage_authorized",
        ):
            self.assertIs(getattr(result, name), False, name)
        self.assertIn("HOLD", result.state)

    def test_three_bot_shared_perp_shape_never_authorizes(self):
        requests = []
        def transport(payload):
            requests.append(payload.copy())
            return encoded(perp())
        for _ in ("daily", "intraday", "aggressive"):
            result = inspect_unwired_signer_free_account_view(
                account=ACCOUNT, network="testnet", test_transport=transport,
            )
            self.assertEqual(result.state, "PARSED_UNTRUSTED_INFO_FIXTURE_HOLD")
            self.assertEqual(result.equity, 100.0)
            self.assertEqual(result.positions["SOL"]["size"], -0.25)
            self.assertEqual(result.observed_read_types, ("clearinghouseState",))
            self.assert_no_authority(result)
        self.assertEqual(requests, [
            {"type": "clearinghouseState", "user": ACCOUNT, "dex": ""},
        ] * 3)

    def test_low_equity_spot_fallback_requires_second_read(self):
        requests = []
        def transport(payload):
            requests.append(payload["type"])
            return encoded(perp(equity="5")) if len(requests) == 1 else encoded({
                "balances": [{"coin": "USDC", "total": "23.5"}],
            })
        result = inspect_unwired_signer_free_account_view(
            account=ACCOUNT, network="testnet", test_transport=transport,
        )
        self.assertEqual(requests, ["clearinghouseState", "spotClearinghouseState"])
        self.assertEqual(result.equity, 23.5)
        self.assert_no_authority(result)

    def test_denies_bad_scope_or_missing_callback_without_read(self):
        called = []
        def transport(payload):
            called.append(payload)
            return encoded(perp())
        for account, network, callback in (
            (ACCOUNT.upper(), "testnet", transport),
            ("0x" + "2" * 40, "testnet", transport),
            ("0x" + "a" * 39, "testnet", transport),
            (ACCOUNT, "mainnet", transport),
            (ACCOUNT, True, transport),
            (ACCOUNT, "testnet", None),
        ):
            with self.subTest(account=account, network=network):
                result = inspect_unwired_signer_free_account_view(
                    account=account, network=network, test_transport=callback,
                )
                self.assertEqual(result.state, "HOLD")
                self.assert_no_authority(result)
        self.assertEqual(called, [])

    def test_invalid_data_and_callback_fail_closed(self):
        failures = (
            b"", b"{", b"[]", b'{"a":1,"a":2}', b'{"x":NaN}',
            b" " * 131073, encoded(perp(equity="NaN")),
            encoded(perp(positions=[{
                "position": {"coin": "SOL", "szi": "Infinity"},
            }])),
        )
        for raw in failures:
            with self.subTest(raw=raw[:30]):
                result = inspect_unwired_signer_free_account_view(
                    account=ACCOUNT, network="testnet",
                    test_transport=lambda _: raw,
                )
                self.assertEqual(result.state, "HOLD")
                self.assert_no_authority(result)
        for error in (TimeoutError("secret"), RuntimeError("secret")):
            def fails(_):
                raise error
            result = inspect_unwired_signer_free_account_view(
                account=ACCOUNT, network="testnet", test_transport=fails,
            )
            self.assertEqual(result.state, "HOLD")
            self.assertNotIn("secret", repr(result))
            self.assert_no_authority(result)

    def test_market_mid_prices_and_precision_are_untrusted_not_trade_authority(self):
        seen = []
        def fake(request):
            seen.append(request.copy())
            if request["type"] == "allMids":
                return encoded({"SOL": "100.25", "AVAX": "21.05"})
            if request["type"] == "meta":
                return encoded({"universe": [
                    {"name": "SOL", "szDecimals": 2},
                    {"name": "AVAX", "szDecimals": 1},
                ]})
            self.fail("unknown read type")
        view = inspect_unwired_market_reference_view(
            coins=("SOL", "AVAX"), network="testnet", test_transport=fake,
        )
        self.assertEqual(view.state, "PARSED_UNTRUSTED_MARKET_FIXTURE_HOLD")
        self.assertTrue(view.market_reference_parsed)
        self.assertEqual(view.mid_prices, {"SOL": "100.25", "AVAX": "21.05"})
        self.assertEqual(view.size_decimals, {"SOL": 2, "AVAX": 1})
        self.assertEqual(view.observed_read_types, ("allMids", "meta"))
        self.assertEqual(seen, [
            {"type": "allMids", "dex": ""},
            {"type": "meta", "dex": ""},
        ])
        for name in (
            "exchange_origin_authenticated", "market_freshness_verified",
            "asset_constraints_verified", "prices_authorized_for_orders",
            "order_authorized", "leverage_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(view, name), False, name)

    def test_market_reference_refuses_missing_prices_or_precision(self):
        bad_prices = (
            {}, {"SOL": "0"}, {"SOL": "-1"}, {"SOL": "NaN"},
            {"SOL": "Infinity"}, {"SOL": "1e1000"},
            {"SOL": "1000000000001"}, {"SOL": 25},
        )
        for mid in bad_prices:
            with self.subTest(mid=mid):
                result = inspect_unwired_market_reference_view(
                    coins=("SOL",), network="testnet",
                    test_transport=lambda request: encoded(
                        mid if request["type"] == "allMids" else
                        {"universe": [{"name": "SOL", "szDecimals": 2}]}
                    ),
                )
                self.assertEqual(result.state, "HOLD")
                self.assertFalse(result.market_reference_parsed)
        for universe in (
            [],
            [{"name": "SOL"}],
            [{"name": "SOL", "szDecimals": "2"}],
            [{"name": "SOL", "szDecimals": True}],
            [{"name": "SOL", "szDecimals": 9}],
            [{"name": "SOL", "szDecimals": 2, "isDelisted": True}],
            [{"name": "SOL", "szDecimals": 2},
             {"name": "SOL", "szDecimals": 2}],
        ):
            with self.subTest(universe=universe):
                result = inspect_unwired_market_reference_view(
                    coins=("SOL",), network="testnet",
                    test_transport=lambda request: encoded(
                        {"SOL": "50"} if request["type"] == "allMids"
                        else {"universe": universe}
                    ),
                )
                self.assertEqual(result.state, "HOLD")
                self.assertFalse(result.market_reference_parsed)

    def test_market_reference_bad_scope_and_callback_fail_closed(self):
        requests = []
        def fake(request):
            requests.append(request)
            return encoded({"SOL": "10"})
        for coins, network, callback in (
            ((), "testnet", fake),
            (("SOL", "SOL"), "testnet", fake),
            (("sol",), "testnet", fake),
            (("SOL",), "mainnet", fake),
            (("SOL",), True, fake),
            (("SOL",), "testnet", None),
        ):
            with self.subTest(coins=coins, network=network):
                result = inspect_unwired_market_reference_view(
                    coins=coins, network=network, test_transport=callback,
                )
                self.assertEqual(result.state, "HOLD")
        self.assertEqual(requests, [])
        for bad in (b"not JSON", b'{"SOL":"10","SOL":"20"}',
                    b" " * 131073):
            result = inspect_unwired_market_reference_view(
                coins=("SOL",), network="testnet",
                test_transport=lambda _: bad,
            )
            self.assertEqual(result.state, "HOLD")
            self.assertFalse(result.market_reference_parsed)
        def fail(_):
            raise TimeoutError("do-not-leak")
        result = inspect_unwired_market_reference_view(
            coins=("SOL",), network="testnet", test_transport=fail,
        )
        self.assertEqual(result.state, "HOLD")
        self.assertNotIn("do-not-leak", repr(result))

    def test_pr41_collector_canonical_read_envelopes_match(self):
        """Cross-PR #41 frozen request format compatibility, MOCK only.

        Matches PR #41's six_frame_request_contract_offline at
        13ce00001e3116c6e9cbc4c3b98feb87b3e33f08. This checks local
        syntax, NOT whether a future /info gateway is approved or trusted.
        """
        account_requests = []
        def account_transport(request):
            account_requests.append(request.copy())
            return encoded(perp(equity="5")) if request["type"] == "clearinghouseState" else encoded({
                "balances": [{"coin": "USDC", "total": "22"}],
            })
        result = inspect_unwired_signer_free_account_view(
            account=ACCOUNT, network="testnet",
            test_transport=account_transport,
        )
        self.assertTrue(result.fixture_parsed)
        self.assert_no_authority(result)
        expected_clearing = {
            "type": "clearinghouseState", "user": ACCOUNT, "dex": "",
        }
        expected_spot = {
            "type": "spotClearinghouseState", "user": ACCOUNT,
        }
        self.assertEqual(account_requests, [expected_clearing, expected_spot])
        # PR #41's first and sixth reconciliation frames use exactly
        # this sorted, separator-minimized body, including the empty DEX.
        canonical = lambda obj: json.dumps(
            obj, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("ascii")
        self.assertEqual(canonical(account_requests[0]), canonical(expected_clearing))
        self.assertEqual(
            canonical(account_requests[0]),
            b'{"dex":"","type":"clearinghouseState","user":"' +
            ACCOUNT.encode("ascii") + b'"}',
        )
        # Spot fallback is a separate read, NOT part of PR #41's six-frame
        # reconciliation. No order or close authority is implied.
        self.assertEqual(
            canonical(account_requests[1]),
            b'{"type":"spotClearinghouseState","user":"' +
            ACCOUNT.encode("ascii") + b'"}',
        )

        market_requests = []
        def market_transport(request):
            market_requests.append(request.copy())
            return encoded({"SOL": "95"}) if request["type"] == "allMids" else encoded({
                "universe": [{"name": "SOL", "szDecimals": 2}],
            })
        market = inspect_unwired_market_reference_view(
            coins=("SOL",), network="testnet",
            test_transport=market_transport,
        )
        self.assertEqual(market.state, "PARSED_UNTRUSTED_MARKET_FIXTURE_HOLD")
        self.assertEqual(market_requests, [
            {"type": "allMids", "dex": ""},
            {"type": "meta", "dex": ""},
        ])
        self.assertEqual(
            tuple(canonical(x) for x in market_requests),
            (b'{"dex":"","type":"allMids"}',
             b'{"dex":"","type":"meta"}'),
        )
        self.assertFalse(market.order_authorized)
        self.assertFalse(market.prices_authorized_for_orders)

    def test_module_import_graph_excludes_network_signing_and_secrets(self):
        path = Path(__file__).with_name("signer_free_readonly_client_unwired.py")
        imports = set()
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {
            "dataclasses", "decimal", "json", "re",
            "sender_review.signer_free_account_view_offline",
        })
        source = path.read_text("utf-8")
        for forbidden in ("os.environ", "HL_PRIVATE_KEY", "Exchange(", "Info("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
