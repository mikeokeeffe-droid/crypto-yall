"""Offline three-bot ambiguous-order recovery regression matrix.

No network, wallet, exchange, Supabase or production credentials are involved.
The same conservative policy must apply to every strategy identity.
"""
import unittest

from entry_lifecycle_staging import EntryLifecycle, Phase
from order_reconciliation_staging import OrderOutcome
from entry_recovery_decision_staging import (
    Decision, PositionEvidence, decide_recovery,
)
from partial_fill_accounting_staging import reconcile_fill_snapshot


BOTS = ("daily", "intraday", "aggressive")


class ThreeBotUncertainOrderMatrix(unittest.TestCase):
    def submitted(self):
        lifecycle = EntryLifecycle()
        self.assertTrue(lifecycle.acquire(
            reserved=True, claimed=True, exchange_flat=True,
            no_open_orders=True))
        self.assertTrue(lifecycle.submit())
        return lifecycle

    def test_timeout_restart_and_replay_never_duplicate(self):
        for bot in BOTS:
            with self.subTest(bot=bot):
                original = self.submitted()
                original.observe(OrderOutcome.UNKNOWN)
                restored = EntryLifecycle(phase=original.phase)
                for _ in range(3):
                    self.assertFalse(restored.acquire(
                        reserved=True, claimed=True,
                        exchange_flat=True, no_open_orders=True))
                    self.assertFalse(restored.resolve_rejection(
                        order_final=True, exchange_flat=True))
                    self.assertEqual(restored.phase, Phase.UNCERTAIN)

    def test_partial_fill_cannot_release_unknown_intent(self):
        for bot in BOTS:
            with self.subTest(bot=bot):
                lifecycle = self.submitted()
                lifecycle.observe(OrderOutcome.UNKNOWN)
                snapshot = reconcile_fill_snapshot(
                    requested_size=10, fill_sizes=[2.5], order_final=True)
                self.assertEqual(decide_recovery(
                    order_final=True, fill_snapshot=snapshot,
                    position=PositionEvidence(True, 2.5)), Decision.OWN_POSITION)
                self.assertEqual(lifecycle.phase, Phase.UNCERTAIN)
                lifecycle.observe(OrderOutcome.FILLED)
                self.assertEqual(lifecycle.phase, Phase.OWNED)
                self.assertFalse(lifecycle.acquire(
                    reserved=True, claimed=True,
                    exchange_flat=True, no_open_orders=True))

    def test_no_fill_requires_authoritative_finality_and_flatness(self):
        for bot in BOTS:
            with self.subTest(bot=bot):
                empty = reconcile_fill_snapshot(
                    requested_size=10, fill_sizes=[], order_final=True)
                for finality, position, expected in (
                    (None, PositionEvidence(True, 0), Decision.KEEP_FENCED),
                    (False, PositionEvidence(True, 0), Decision.KEEP_FENCED),
                    (True, PositionEvidence(False, 0), Decision.KEEP_FENCED),
                    (True, PositionEvidence(True, 1), Decision.OWN_POSITION),
                    (True, PositionEvidence(True, 0), Decision.RELEASE_NO_FILL),
                ):
                    self.assertEqual(decide_recovery(
                        order_final=finality, fill_snapshot=empty,
                        position=position), expected)

    def test_incomplete_fill_evidence_always_stays_fenced(self):
        for bot in BOTS:
            with self.subTest(bot=bot):
                for invalid in ([-1], [float("nan")], [11], [float("inf")]):
                    snapshot = reconcile_fill_snapshot(
                        requested_size=10, fill_sizes=invalid, order_final=True)
                    self.assertIsNone(snapshot)
                    self.assertEqual(decide_recovery(
                        order_final=True, fill_snapshot=snapshot,
                        position=PositionEvidence(True, 0)), Decision.KEEP_FENCED)


if __name__ == "__main__":
    unittest.main()
