"""Fail-closed source-only quarantine tests for signer-enabled legacy paths."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sender_review.review_only_quarantine_offline import (
    check_worker_source, check_workflow_source, review_fixture_quarantine,
    check_frozen_legacy_content, git_blob_fingerprint,
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

    def test_frozen_live_files_detect_one_byte_drift(self):
        # The eight checked-in live paths must exactly match the reviewed
        # main-branch Git blobs, not merely pass a permissive regex scan.
        self.assertEqual(check_frozen_legacy_content(ROOT), ())
        with TemporaryDirectory() as folder:
            root = Path(folder)
            paths = (
                "hyperliquid_executor.py", "intraday_executor.py",
                "aggressive_executor.py", "intraday_profit_protection.py",
                "aggressive_profit_protection.py",
                ".github/workflows/execute-trades.yml",
                ".github/workflows/execute-intraday.yml",
                ".github/workflows/execute-aggressive.yml",
            )
            for path in paths:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / path).read_bytes())
            self.assertEqual(check_frozen_legacy_content(root), ())
            # A non-semantic edit must still force independent re-audit.
            changed = root / paths[0]
            changed.write_bytes(changed.read_bytes() + b"\\n")
            issues = check_frozen_legacy_content(root)
            self.assertEqual(len(issues), 1)
            self.assertIn(paths[0], issues[0])
            # No automatic permission to approve drift by changing a pin.
            self.assertFalse(review_fixture_quarantine(root)[
                "quarantine_checks_pass"
            ])

    def test_git_blob_fingerprint_type_and_content(self):
        import hashlib
        data = b"example\n"
        expected = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest()
        self.assertEqual(git_blob_fingerprint(data), expected)
        with self.assertRaises(TypeError):
            git_blob_fingerprint("example")

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
