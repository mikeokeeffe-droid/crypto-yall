"""CI-only regression for historic report writes and mid-run workspace resets."""
from pathlib import Path
import tempfile
import unittest

from sender_review.legacy_cutover_audit import ROOT
from sender_review.legacy_report_publisher_audit_offline import (
    WORKFLOWS, inspect_legacy_report_publishers_offline,
)


class LegacyReportPublisherAuditTests(unittest.TestCase):
    def test_current_three_bot_report_hazards_are_visible_without_live_actions(self):
        result = inspect_legacy_report_publishers_offline()
        self.assertEqual(result.decision, "NO_GO")
        self.assertFalse(result.production_migration_ready)
        self.assertFalse(result.report_delivery_verified)
        self.assertFalse(result.safe_workspace_proven)
        self.assertEqual(len(result.findings), 3)
        for evidence in result.findings:
            with self.subTest(workflow=evidence.workflow):
                self.assertTrue(evidence.source_read)
                self.assertTrue(evidence.report_step_present)
                self.assertTrue(evidence.grants_contents_write)
                self.assertTrue(evidence.directly_pushes_main)
                self.assertTrue(evidence.resets_checkout_to_main)
                self.assertTrue(evidence.report_failure_nonfatal)
        self.assertFalse(result.findings[0].protection_monitor_follows_report)
        self.assertTrue(result.findings[1].protection_monitor_follows_report)
        self.assertTrue(result.findings[2].protection_monitor_follows_report)

    def test_missing_workflow_and_no_report_step_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = inspect_legacy_report_publishers_offline(root)
            self.assertEqual(missing.decision, "NO_GO")
            self.assertTrue(all(not f.source_read for f in missing.findings))
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            for filename in WORKFLOWS:
                (workflows / filename).write_text(
                    "name: offline fixture\npermissions:\n  contents: read\n"
                    "jobs:\n  check:\n    steps:\n      - name: Safe step\n        run: echo safe\n",
                    encoding="utf-8",
                )
            absent = inspect_legacy_report_publishers_offline(root)
            self.assertTrue(all(f.source_read for f in absent.findings))
            self.assertTrue(all(not f.report_step_present for f in absent.findings))
            self.assertTrue(all(not f.directly_pushes_main for f in absent.findings))
            self.assertEqual(absent.decision, "NO_GO")

    def test_reordered_monitor_is_not_falsely_reported_as_after_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            for filename in WORKFLOWS:
                text = (ROOT / ".github" / "workflows" / filename).read_text("utf-8")
                if filename == "execute-intraday.yml":
                    text = text.replace(
                        "      - name: Monitor Intraday protection until next strategy run",
                        "      - name: Renamed monitoring step",
                    )
                (workflows / filename).write_text(text, encoding="utf-8")
            result = inspect_legacy_report_publishers_offline(root)
            self.assertFalse(result.findings[1].protection_monitor_follows_report)
            self.assertTrue(result.findings[2].protection_monitor_follows_report)
            self.assertEqual(result.decision, "NO_GO")


if __name__ == "__main__":
    unittest.main()
