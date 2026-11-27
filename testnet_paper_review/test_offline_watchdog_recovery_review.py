from dataclasses import replace
import unittest
from testnet_paper_review.test_offline_watchdog_receipt_bridge import flat
from testnet_paper_review.offline_watchdog_recovery_review import review_recovery, RecoveryHold

class RecoveryReviewTests(unittest.TestCase):
    def review(self, **changes):
        args = dict(ledger_view=(0,"READ_FAILED"), backup_sha256="a"*64,
                    first_receipt=flat(), second_receipt=flat(),
                    first_sample_s=100, second_sample_s=102, now_s=103)
        args.update(changes)
        return review_recovery(**args)

    def test_proposal_never_grants_authority(self):
        r = self.review()
        self.assertEqual(r.incident,"READ_FAILED")
        self.assertFalse(r.may_clear)
        self.assertFalse(r.may_trade)
        self.assertFalse(r.may_close)

    def test_ineligible_incidents(self):
        for state in ((1,"READ_FAILED"),(0,None),(0,"UNKNOWN_ACK"),
                      (0,"MISSING_STOP"),(0,"FOREIGN_EXPOSURE"),
                      (False,"READ_FAILED"),(0,"INTERRUPTED_OR_COMPETING_WATCH")):
            with self.subTest(state=state), self.assertRaises(RecoveryHold):
                self.review(ledger_view=state)

    def test_invalid_digest(self):
        for digest in ("",None,"z"*64):
            with self.assertRaises(RecoveryHold):
                self.review(backup_sha256=digest)

    def test_stale_replayed_future_times(self):
        for changes in (dict(now_s=131),dict(second_sample_s=100),
                        dict(second_sample_s=104),dict(first_sample_s=True)):
            with self.assertRaises(RecoveryHold):
                self.review(**changes)

    def test_exposure_or_consumed_entry_blocks(self):
        for r in (None,replace(flat(),position_count=1),
                  replace(flat(),open_order_count=1),
                  replace(flat(),stage="ENTRY_CONSUMED_BUT_FLAT"),
                  replace(flat(),may_trade=True),replace(flat(),needs_operator=True)):
            for field in ("first_receipt","second_receipt"):
                with self.assertRaises(RecoveryHold):
                    self.review(**{field:r})

if __name__ == "__main__":
    unittest.main()
