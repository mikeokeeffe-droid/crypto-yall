"""P3 review-only recovery triage decision table regression tests.

All synthetic events, even apparently consistent ones, remain HOLD with
no operator authority, signer, order send, retry, or fence release.
"""
import ast
from dataclasses import replace
from pathlib import Path
import unittest

from sender_review.protective_recovery_simulator_offline import RecoveryReview
from sender_review.recovery_triage_decision_table_offline import (
    OfflineRecoveryTriage, triage_simulated_recovery_offline,
)
from sender_review.test_protective_recovery_simulator_offline import (
    assess, order, position, close, NONCE,
)


class RecoveryTriageDecisionTableOfflineTests(unittest.TestCase):
    def assert_denied(self, result):
        self.assertIs(type(result), OfflineRecoveryTriage)
        self.assertEqual(result.state, "HOLD")
        self.assertFalse(result.trusted_exchange_state)
        self.assertFalse(result.trusted_position_ownership)
        self.assertFalse(result.retry_authorized)
        self.assertFalse(result.protective_close_authorized)
        self.assertFalse(result.submit_authorized)
        self.assertFalse(result.fence_release_authorized)
        self.assertTrue(result.evidence_needed)
        self.assertIn("manual", result.escalation)

    def test_six_order_outcomes_have_distinct_hold_reconciliation_categories(self):
        outcomes = (
            ("not_sent", "0", "0.16", "no-send-unproven"),
            ("unknown_ack", "0", "0.16", "unknown-ack"),
            ("open", "0", "0.16", "open-order"),
            ("partial", "0.04", "0.12", "partial-exposure"),
            ("canceled", "0.04", "0.12", "canceled-unverified"),
            ("filled", "0.16", "0", "filled-unverified"),
        )
        for bot in ("daily", "intraday", "aggressive"):
            for status, filled, remaining, expected in outcomes:
                with self.subTest(bot=bot, status=status):
                    simulated = assess(
                        fixture_bot=bot, position=position(bot=bot),
                        order=order(
                            status=status, cumulative_fill=filled,
                            remaining_size=remaining,
                        ),
                    )
                    self.assertEqual(simulated.state, "HOLD")
                    self.assertTrue(simulated.fixture_matched)
                    triage = triage_simulated_recovery_offline(simulated)
                    self.assertEqual(triage.category, expected)
                    self.assert_denied(triage)

    def test_conflicting_or_absent_evidence_never_implies_safe_retry(self):
        scenarios = (
            (dict(order=None), "missing-provenance"),
            (dict(order=order(coin="AVAX")), "conflicting-provenance"),
            (dict(seen_nonces=frozenset({NONCE})), "nonce-contention"),
            (dict(position=position(active_nonce="e" * 32)),
             "fence-contention"),
            (dict(order=order(cumulative_fill="0.08", remaining_size="0.10")),
             "contradictory-fills"),
        )
        for changes, expected in scenarios:
            with self.subTest(changes=changes):
                triage = triage_simulated_recovery_offline(assess(**changes))
                self.assertEqual(triage.category, expected)
                self.assert_denied(triage)

    def test_stale_unmatched_or_unknown_fixtures_stay_incomplete(self):
        for simulated in (
            assess(position=position(position_age_seconds=12)),
            assess(body=close(reduce_only=False)),
            assess(order=order(status="unknown-future-status")),
            RecoveryReview(reason="unknown-ack-permanent-hold"),
            RecoveryReview(reason="no-such-category", fixture_matched=True),
        ):
            with self.subTest(reason=simulated.reason):
                triage = triage_simulated_recovery_offline(simulated)
                self.assertEqual(triage.category, "incomplete-or-invalid-fixture")
                self.assert_denied(triage)

    def test_forged_auth_signing_permissions_and_non_hold_are_rejected(self):
        base = assess()
        self.assertTrue(base.fixture_matched)
        for field in (
            "runtime_identity_authenticated", "exchange_snapshot_verified",
            "position_ownership_verified", "nonce_reserved",
            "fence_released", "retry_authorized", "close_authorized",
            "submit_authorized", "signing_enabled",
        ):
            with self.subTest(field=field):
                simulated = replace(base, **{field: True})
                triage = triage_simulated_recovery_offline(simulated)
                self.assertEqual(triage.category, "invalid-or-authorizing-input")
                self.assert_denied(triage)
        for invalid in (
            replace(base, state="READY"),
            replace(base, fixture_matched=1),
            None,
            {"state": "HOLD", "reason": base.reason},
        ):
            with self.subTest(invalid=repr(invalid)):
                triage = triage_simulated_recovery_offline(invalid)
                self.assertEqual(triage.category, "invalid-or-authorizing-input")
                self.assert_denied(triage)

    def test_module_is_pure_offline_no_network_database_or_signer_imports(self):
        source = Path(__file__).with_name(
            "recovery_triage_decision_table_offline.py"
        ).read_text("utf-8")
        modules = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                modules.update(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module)
        self.assertEqual(modules, {
            "dataclasses",
            "sender_review.protective_recovery_simulator_offline",
        })


if __name__ == "__main__":
    unittest.main()
