"""Tests of source-only legacy cutover blocker inventory (no imports of bots)."""
from pathlib import Path
import tempfile
import unittest

from sender_review.legacy_cutover_audit import (
    ROOT, LEGACY, inspect_current_checkout, inspect_python_mutation_sites,
    make_no_go_report,
)


class LegacyCutoverAuditTests(unittest.TestCase):
    def test_original_three_bots_remain_no_go(self):
        snapshot = inspect_current_checkout()
        self.assertEqual(set(snapshot), {"daily", "intraday", "aggressive"})
        for bot, result in snapshot.items():
            with self.subTest(bot=bot):
                self.assertTrue(result.signing_key_in_workflow)
                self.assertFalse(result.oidc_token_permission_present)
                self.assertTrue(result.has_signer_backed_bootstrap)
                self.assertFalse(result.can_prove_no_signing_or_order_egress)
                self.assertFalse(result.ready_for_cutover)
                self.assertTrue(result.direct_mutations)
                self.assertTrue(result.workflow_dispatch_available)
                self.assertTrue(set(result.entrypoints))
                self.assertTrue(any("market_open@" in x for x in result.direct_mutations))
                self.assertTrue(any("market_close@" in x for x in result.direct_mutations))
                self.assertTrue(any("update_leverage@" in x for x in result.direct_mutations))
                self.assertTrue(result.unsized_market_close_lines)
        self.assertIn("intraday_profit_protection.py", snapshot["intraday"].entrypoints)
        self.assertIn("aggressive_profit_protection.py", snapshot["aggressive"].entrypoints)

    def test_no_go_output_is_explicit_even_if_snapshot_is_green(self):
        report = make_no_go_report()
        self.assertEqual(report["status"], "NO_GO")
        self.assertFalse(any(x["ready_for_cutover"] for x in report["workers"].values()))
        self.assertEqual(len(report["release_gates_unproven"]), 6)

    def test_static_source_parser_never_imports_or_runs_executor(self):
        source = """
from typing import Any
def get_client():
    raise RuntimeError('HL_PRIVATE_KEY not callable')
def execute(exchange, coin):
    exchange.market_open(coin, True, 1)
    exchange.market_close(coin)
    exchange.market_close(coin, sz=1)
    exchange.update_leverage(2, coin, True)
"""
        sinks, unsafe_closes, signer = inspect_python_mutation_sites(source)
        self.assertTrue(signer)
        self.assertIn("market_open@6", sinks)
        self.assertEqual(unsafe_closes, (7,))

    def test_drift_or_missing_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for item in LEGACY.values():
                for file in (item["workflow"], item["executor"], item["wrapper"]):
                    if file is None:
                        continue
                    target=root/file
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source=(ROOT/file).read_text("utf-8")
                    target.write_text(source, encoding="utf-8")
            self.assertEqual(set(inspect_current_checkout(root)), set(LEGACY))
            (root/LEGACY["daily"]["workflow"]).write_text(
                "name: replaced\non: workflow_dispatch\n", encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                inspect_current_checkout(root)
            # Restore workflow before checking missing-file failure,
            # otherwise the earlier deliberate drift fails first.
            (root/LEGACY["daily"]["workflow"]).write_text(
                (ROOT/LEGACY["daily"]["workflow"]).read_text("utf-8"),
                encoding="utf-8",
            )
            (root/LEGACY["intraday"]["executor"]).unlink()
            with self.assertRaises(FileNotFoundError):
                inspect_current_checkout(root)

    def test_no_secret_material_or_trading_transport_used_in_audit_module(self):
        import ast
        source=(ROOT/"sender_review/legacy_cutover_audit.py").read_text("utf-8")
        tree=ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(x.name in {
                    "__future__", "ast", "json", "re", "sys"
                } for x in node.names))
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, {
                    "__future__", "dataclasses", "pathlib", "typing"
                })


if __name__ == "__main__":
    unittest.main()
