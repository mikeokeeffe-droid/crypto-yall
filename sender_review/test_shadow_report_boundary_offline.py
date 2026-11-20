"""No-order output contract for synthetic shadow-worker status reporting."""
import ast
from dataclasses import replace
from pathlib import Path
import unittest

from sender_review.composed_shadow_worker_offline import (
    inspect_shadow_worker_cycle_offline,
)
from sender_review.shadow_report_boundary_offline import (
    inspect_shadow_report_boundary_offline,
)


def account():
    return {"marginSummary": {"accountValue": "100"}, "assetPositions": []}


class ShadowReportBoundaryTests(unittest.TestCase):
    def preview(self, bot="daily"):
        return inspect_shadow_worker_cycle_offline(
            bot=bot, user_state=account(), synthetic_now_epoch=1700000000,
            max_positions=2, signals={
                "SOL-USD": {"action": "buy", "bull_conf": 0.9, "osc": 0.9},
            },
        )

    def test_aggregate_report_can_never_be_sent_or_signed(self):
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                cycle = self.preview(bot=bot)
                report = inspect_shadow_report_boundary_offline(cycle=cycle)
                self.assertEqual(report.state, "METADATA_ONLY_SHADOW_REPORT_HOLD")
                self.assertTrue(report.review_ready)
                self.assertEqual(report.deferred_entry_count, 1)
                self.assertEqual(report.close_candidate_count, 0)
                self.assertIsNone(report.body)
                self.assertIsNone(report.method)
                self.assertIsNone(report.path)
                self.assertIsNone(report.authorization)
                self.assertFalse(report.request_authorized)
                self.assertFalse(report.submit_authorized)
                self.assertFalse(report.close_authorized)
                self.assertFalse(report.signing_enabled)
                self.assertNotIn("SOL", repr(report))
                self.assertNotIn("open_long", repr(report))

    def test_malformed_or_spoofed_cycle_cannot_cross_boundary(self):
        valid = self.preview()
        cases = (
            None, {}, "GO",
            replace(valid, state="GO"),
            replace(valid, submit_authorized=True),
            replace(valid, request_authorized=True),
            replace(valid, close_authorized=True),
            replace(valid, signing_enabled=True),
            replace(valid, additional_spot_read_needed={
                "coin": "SOL", "authorization": "do-not-export",
            }),
            replace(valid, additional_spot_read_needed="false"),
            replace(valid, additional_spot_read_needed=1),
            replace(valid, exchange_origin_authenticated=True),
            replace(valid, position_ownership_verified=True),
            replace(valid, close_review_proposals=[]),
            replace(valid, deferred_flip_entry_proposals=tuple(
                valid.deferred_entry_proposals * 2
            )),
        )
        for candidate in cases:
            with self.subTest(candidate=str(candidate)[:100]):
                report = inspect_shadow_report_boundary_offline(cycle=candidate)
                self.assertEqual(report.state, "HOLD")
                self.assertFalse(report.review_ready)
                self.assertFalse(report.submit_authorized)

    def test_untrusted_account_data_keeps_report_in_hold(self):
        bad = inspect_shadow_worker_cycle_offline(
            bot="daily", user_state=None, signals={}, max_positions=1,
            synthetic_now_epoch=1700000000,
        )
        report = inspect_shadow_report_boundary_offline(cycle=bad)
        self.assertEqual(report.state, "HOLD")
        self.assertEqual(report.deferred_entry_count, 0)

    def test_no_network_signer_sdk_or_database_import(self):
        src = Path(__file__).with_name("shadow_report_boundary_offline.py")
        imports = set()
        for node in ast.walk(ast.parse(src.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(x.name for x in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {
            "dataclasses", "sender_review.composed_shadow_worker_offline",
        })


if __name__ == "__main__":
    unittest.main()
