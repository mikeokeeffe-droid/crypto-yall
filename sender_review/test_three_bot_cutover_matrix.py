"""Source-only cutover coverage tests. Never instantiate live bots."""
from pathlib import Path
import tempfile
import unittest

from sender_review.legacy_cutover_audit import LEGACY, ROOT
from sender_review.three_bot_cutover_matrix import (
    _CUTOVER_REQUIREMENTS,
    _EXPECTED,
    build_no_go_matrix,
    inspect_cutover_surfaces,
)


class ThreeBotCutoverMatrixTests(unittest.TestCase):
    def test_each_legacy_path_and_key_assignment_is_accounted_for(self):
        bots = inspect_cutover_surfaces()
        self.assertEqual(set(bots), {"daily", "intraday", "aggressive"})
        for bot, item in bots.items():
            with self.subTest(bot=bot):
                self.assertEqual(
                    item.execution_invocations, _EXPECTED[bot]["execution_invocations"]
                )
                self.assertEqual(
                    item.exposed_signer_env_assignments,
                    _EXPECTED[bot]["key_injections"],
                )
                self.assertEqual(item.mutation_counts, {
                    "market_close_explicit_size": 1,
                    "market_close_unsized": 1,
                    "market_open": 1,
                    "update_leverage": 1,
                })
                self.assertFalse(item.signer_free_runtime_proven)
                self.assertFalse(item.safe_close_proven)
                self.assertFalse(item.migration_approved)
        self.assertEqual(bots["daily"].execution_invocations, 1)
        self.assertEqual(bots["intraday"].execution_invocations, 2)
        self.assertEqual(bots["aggressive"].execution_invocations, 2)

    def test_no_go_cannot_be_changed_by_clean_static_results(self):
        report = build_no_go_matrix()
        self.assertEqual(report["status"], "NO_GO")
        self.assertEqual(len(report["critical_requirements_unproven"]),
                         len(_CUTOVER_REQUIREMENTS))
        self.assertEqual(report["additional_aggressive_action"],
                         "pyramid_long/pyramid_short")

    def test_changed_secret_execution_or_mutation_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for item in LEGACY.values():
                for relative in (
                    item["workflow"], item["executor"], item["wrapper"],
                ):
                    if relative is None:
                        continue
                    dest=root/relative
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    dest.write_bytes((ROOT/relative).read_bytes())
            self.assertEqual(set(inspect_cutover_surfaces(root)), set(LEGACY))

            daily=root/LEGACY["daily"]["workflow"]
            orig=daily.read_text("utf-8")
            daily.write_text(orig.replace(
                "HL_PRIVATE_KEY: ${{ secrets.HL_PRIVATE_KEY }}",
                "HL_PRIVATE_KEY_RENAMED: ${{ secrets.HL_PRIVATE_KEY }}",
            ),encoding="utf-8")
            with self.assertRaises(ValueError):
                inspect_cutover_surfaces(root)
            daily.write_text(orig,encoding="utf-8")

            executor=root/LEGACY["daily"]["executor"]
            orig_exec=executor.read_text("utf-8")
            executor.write_text(orig_exec + "\ndef dangerous(e):\n    e.cancel(1, 'SOL')\n",
                                encoding="utf-8")
            with self.assertRaises(ValueError):
                inspect_cutover_surfaces(root)
            executor.write_text(orig_exec,encoding="utf-8")

            intraday=root/LEGACY["intraday"]["workflow"]
            orig_intra=intraday.read_text("utf-8")
            intraday.write_text(orig_intra.replace(
                "python intraday_profit_protection.py",
                "python innocent_no_trading.py",
            ),encoding="utf-8")
            with self.assertRaises(ValueError):
                inspect_cutover_surfaces(root)

    def test_audit_module_imports_no_exchange_or_network_packages(self):
        import ast
        source=(ROOT/"sender_review/three_bot_cutover_matrix.py").read_text("utf-8")
        tree=ast.parse(source)
        names=set()
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                names.update(x.name for x in node.names)
            elif isinstance(node,ast.ImportFrom):
                names.add(node.module)
        self.assertEqual(names,{
            "__future__","ast","collections","dataclasses",
            "json","pathlib","re","sender_review.legacy_cutover_audit",
        })


if __name__ == "__main__":
    unittest.main()
