"""Offline Testnet-only selector regression; no network or exchange imports."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sender_review.testnet_only_scope_offline import (
    inspect_testnet_only_scope_offline,
)

ROOT = Path(__file__).resolve().parents[1]


class TestnetOnlyScopeTests(unittest.TestCase):
    def assert_never_authorized(self, result):
        for field in (
            "server_scope_verified", "account_scope_verified",
            "network_egress_verified", "signing_enabled",
            "order_authorized", "close_authorized",
        ):
            self.assertIs(getattr(result, field), False, field)

    def test_exact_testnet_proposal_is_fixed_but_always_hold(self):
        result = inspect_testnet_only_scope_offline(
            proposed_network="testnet",
        )
        self.assertTrue(result.candidate_parsed)
        self.assertEqual(result.state, "REVIEW_ONLY_HOLD")
        self.assertEqual(result.network, "testnet")
        self.assertEqual(result.api_url, "https://api.hyperliquid-testnet.xyz")
        self.assert_never_authorized(result)

    def test_mainnet_typos_missing_nonstring_and_urls_are_denied(self):
        candidates = (
            "mainnet", "MAINNET", "TESTNET", "Testnet", " true ", "true",
            "", None, False, True, 1, [], {}, "testnet ",
            "testnet/mainnet", "te\u0455tnet",
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                result = inspect_testnet_only_scope_offline(
                    proposed_network=candidate,
                )
                self.assertEqual(result.state, "HOLD")
                self.assertIsNone(result.api_url)
                self.assertFalse(result.candidate_parsed)
                self.assert_never_authorized(result)

        for url in (
            "https://api.hyperliquid.xyz",
            "https://api.hyperliquid-testnet.xyz",
            "https://example.invalid",
            "", False,
        ):
            with self.subTest(url=url):
                result = inspect_testnet_only_scope_offline(
                    proposed_network="testnet", proposed_api_url=url,
                )
                self.assertEqual(result.state, "HOLD")
                self.assertIsNone(result.api_url)
                self.assert_never_authorized(result)

    def test_environment_cannot_flip_review_only_scope(self):
        for val in ("false", "FALSE", "1", "", "true"):
            with self.subTest(HL_TESTNET=val):
                with patch.dict(os.environ, {"HL_TESTNET": val}):
                    result = inspect_testnet_only_scope_offline(
                        proposed_network="testnet",
                    )
                    self.assertEqual(result.network, "testnet")
                    self.assertEqual(
                        result.api_url,
                        "https://api.hyperliquid-testnet.xyz",
                    )
                    self.assert_never_authorized(result)

    def test_original_selector_can_choose_mainnet_without_running_bot(self):
        """Characterize legacy risk with AST and fake SDK objects only."""
        source = (ROOT / "hyperliquid_executor.py").read_text("utf-8")
        tree = ast.parse(source)
        matches = [
            n for n in tree.body if isinstance(n, ast.FunctionDef)
            and n.name == "get_client"
        ]
        self.assertEqual(len(matches), 1)
        fn = matches[0]
        fn.decorator_list = []
        fake = SimpleNamespace(
            TESTNET_API_URL="fake://testnet",
            MAINNET_API_URL="fake://mainnet",
        )
        captured = []
        class FakeAccount:
            @staticmethod
            def from_key(_value):
                return object()
        def info(url, **_kwargs):
            captured.append(url)
            return object()
        def exchange(_wallet, url, **_kwargs):
            captured.append(url)
            return object()
        ns = {
            "os": os, "constants": fake, "Account": FakeAccount,
            "Info": info, "Exchange": exchange,
        }
        isolated = ast.fix_missing_locations(
            ast.Module(body=[fn], type_ignores=[])
        )
        exec(compile(isolated, "<isolated-get-client>", "exec"), ns)
        for flag, expected in (
            ("true", "fake://testnet"),
            ("TrUe", "fake://testnet"),
            ("false", "fake://mainnet"),
            ("FALSE", "fake://mainnet"),
            ("", "fake://mainnet"),
        ):
            captured.clear()
            with self.subTest(flag=flag):
                with patch.dict(os.environ, {
                    "HL_PRIVATE_KEY": "synthetic-unused-value",
                    "HL_ACCOUNT_ADDRESS": "synthetic-unused-address",
                    "HL_TESTNET": flag,
                }):
                    ns["get_client"]()
                self.assertEqual(captured, [expected, expected])
        # The legacy behavior remains a risk. Never run these original paths.

    def test_original_three_workflows_still_expose_selector_and_key(self):
        paths = (
            ".github/workflows/execute-trades.yml",
            ".github/workflows/execute-intraday.yml",
            ".github/workflows/execute-aggressive.yml",
        )
        for relative in paths:
            with self.subTest(path=relative):
                data = (ROOT / relative).read_text("utf-8")
                self.assertIn("vars.HL_TESTNET", data)
                self.assertIn("secrets.HL_PRIVATE_KEY", data)

    def test_new_scope_is_stdlib_only_without_environment_or_sdk(self):
        file = Path(__file__).with_name("testnet_only_scope_offline.py")
        imports = set()
        for node in ast.walk(ast.parse(file.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {"dataclasses"})


if __name__ == "__main__":
    unittest.main()
