"""Fail-closed source-only quarantine tests for signer-enabled legacy paths."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sender_review.review_only_quarantine_offline import (
    check_worker_source, check_workflow_source, review_fixture_quarantine,
)
from sender_review.legacy_cutover_audit import LEGACY, ROOT


class ReviewOnlyQuarantineTests(unittest.TestCase):
    def test_current_five_execution_paths_keep_ci_fixtures_out(self):
        result = review_fixture_quarantine()
        self.assertTrue(result["quarantine_checks_pass"], result["issues"])
        self.assertEqual(result["status"], "NO_GO")
        self.assertFalse(result["live_trading_authorized"])
        self.assertFalse(result["signing_authorized"])
        self.assertFalse(result["testnet_authorized"])

    def test_worker_imports_and_fixture_bypasses_are_rejected(self):
        examples = (
            "import sender_review.ci_only_identity_bridge",
            "from sender_review.worker_intent_fixture_builder_offline import build_worker_intent_fixture_offline",
            "import sender_review as fake_auth",
            "from sender_review import ci_only_journal",
            "x = 'sender_review/ci_only_journal.sql'",
            "x = 'SENDER_REVIEW_DISPOSABLE_CI'",
            "x = 'sender_review_test'",
            "if True print('malformed')",
        )
        for source in examples:
            with self.subTest(source=source):
                self.assertTrue(check_worker_source(source))

    def test_original_workflow_cannot_run_fake_sender_or_drop_legacy_baseline(self):
        clean = "name: Execute Trades\nenv:\n  HL_PRIVATE_KEY: ${{ secrets.HL_PRIVATE_KEY }}\n"
        self.assertEqual(check_workflow_source(clean), ())
        for source in (
            clean + "\nrun: python sender_review/ci_only_identity_bridge.py",
            clean + "\nenv:\n  SENDER_REVIEW_DISPOSABLE_CI: '1'",
            clean + "\nrun: python sender_review/test_worker_intent_fixture_builder_offline.py",
            "name: Execute Trades\nrun: python hyperliquid_executor.py\n",
        ):
            with self.subTest(source=source):
                self.assertTrue(check_workflow_source(source))

    def test_missing_legacy_executor_reports_no_go(self):
        # Copy only minimal valid legacy sources into a disposable directory,
        # but omit one executable so the audit cannot report a clean pass.
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for name in (
                "hyperliquid_executor.py", "intraday_executor.py",
                "aggressive_executor.py", "intraday_profit_protection.py",
            ):
                (root / name).write_text("pass\n", encoding="utf-8")
            for info in LEGACY.values():
                p = root / info["workflow"]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("HL_PRIVATE_KEY: fake-fixture-only\n", encoding="utf-8")
            result = review_fixture_quarantine(root)
            self.assertFalse(result["quarantine_checks_pass"])
            self.assertTrue(any(
                "aggressive_profit_protection.py" in issue
                for issue in result["issues"]
            ))
            self.assertEqual(result["status"], "NO_GO")


if __name__ == "__main__":
    unittest.main()
