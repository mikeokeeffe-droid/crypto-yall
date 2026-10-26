"""Conservative offline entry recovery decision tests."""
import unittest
from entry_recovery_decision_staging import decide_recovery, Decision, PositionEvidence
from partial_fill_accounting_staging import reconcile_fill_snapshot

class RecoveryDecisionTests(unittest.TestCase):
    def snapshot(self, sizes):
        return reconcile_fill_snapshot(requested_size=10, fill_sizes=sizes, order_final=True)

    def test_no_fill_and_confirmed_flat_releases(self):
        self.assertEqual(decide_recovery(order_final=True, fill_snapshot=self.snapshot([]),
                                         position=PositionEvidence(True, 0)), Decision.RELEASE_NO_FILL)

    def test_partial_fill_owns_position(self):
        self.assertEqual(decide_recovery(order_final=True, fill_snapshot=self.snapshot([3]),
                                         position=PositionEvidence(True, 3)), Decision.OWN_POSITION)

    def test_exposure_even_without_matching_fills_owns_position(self):
        self.assertEqual(decide_recovery(order_final=True, fill_snapshot=self.snapshot([]),
                                         position=PositionEvidence(True, 2)), Decision.OWN_POSITION)

    def test_unknown_finality_or_position_remains_fenced(self):
        for finality, position in [(None, PositionEvidence(True, 0)),
                                   (False, PositionEvidence(True, 0)),
                                   (True, PositionEvidence(False, 0)),
                                   (True, None)]:
            with self.subTest(finality=finality, position=position):
                self.assertEqual(decide_recovery(order_final=finality,
                    fill_snapshot=self.snapshot([]), position=position), Decision.KEEP_FENCED)

    def test_missing_fill_evidence_remains_fenced(self):
        self.assertEqual(decide_recovery(order_final=True, fill_snapshot=None,
                                         position=PositionEvidence(True, 0)), Decision.KEEP_FENCED)

if __name__ == "__main__":
    unittest.main()
