"""No-network, no-key regression tests for the unwired signer-free read seam."""
import ast
import json
from pathlib import Path
import unittest

from sender_review.signer_free_readonly_client_unwired import (
    inspect_unwired_signer_free_account_view,
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
            {"type": "clearinghouseState", "user": ACCOUNT},
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

    def test_module_import_graph_excludes_network_signing_and_secrets(self):
        path = Path(__file__).with_name("signer_free_readonly_client_unwired.py")
        imports = set()
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {
            "dataclasses", "json", "re",
            "sender_review.signer_free_account_view_offline",
        })
        source = path.read_text("utf-8")
        for forbidden in ("os.environ", "HL_PRIVATE_KEY", "Exchange(", "Info("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
