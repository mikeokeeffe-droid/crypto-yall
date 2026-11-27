"""Synthetic watchdog tests; no public API, service or alert delivery."""
import unittest
from testnet_paper_review.offline_watchdog_policy import (
    WatchdogState, advance, rehearsal_alert
)

class OfflineWatchdogTests(unittest.TestCase):
    def flat(self):
        return advance(WatchdogState(), now=100, sampled_at=99, outcome="FLAT")

    def test_flat_never_authorizes_trading(self):
        state=self.flat()
        self.assertIsNone(state.incident)
        self.assertFalse(state.may_trade)
        self.assertEqual(rehearsal_alert(state),"HOLD_NO_TRADING_AUTHORITY")

    def test_bracket_is_observation_only(self):
        state=advance(self.flat(),now=105,sampled_at=104,outcome="BRACKET_OBSERVED")
        self.assertEqual(state.severity,"ATTENTION")
        self.assertFalse(state.may_trade)

    def test_critical_outcomes_latch_even_after_flat(self):
        for outcome in ("UNVERIFIED","UNKNOWN_ACK","MISSING_STOP","FOREIGN_EXPOSURE",
                        "EMERGENCY_ATTEMPT","READ_FAILED"):
            with self.subTest(outcome=outcome):
                state=advance(self.flat(),now=105,sampled_at=104,outcome=outcome)
                self.assertEqual(state.incident,outcome)
                state=advance(state,now=110,sampled_at=109,outcome="FLAT")
                self.assertEqual(state.incident,outcome)
                self.assertEqual(state.severity,"CRITICAL")
                self.assertFalse(state.may_trade)
                self.assertEqual(rehearsal_alert(state),
                                 "CRITICAL_OPERATOR_INSPECTION_NO_RETRY")

    def test_missing_tick_and_sample_gap(self):
        self.assertEqual(advance(self.flat(),now=131).incident,"SUPERVISOR_TICK_MISSED")
        state=advance(self.flat(),now=120)
        self.assertEqual(advance(state,now=130).incident,"OBSERVATION_GAP")
        self.assertEqual(advance(WatchdogState(),now=100).incident,"NO_INITIAL_OBSERVATION")

    def test_stale_replayed_future_and_bad_clock(self):
        for sampled_at in (99,90,106,float("nan"),None):
            with self.subTest(sampled_at=sampled_at):
                state=advance(self.flat(),now=105,sampled_at=sampled_at,outcome="FLAT")
                self.assertEqual(state.incident,"STALE_OR_REPLAYED_OBSERVATION")
        for now in (99,float("inf"),True):
            self.assertEqual(advance(self.flat(),now=now).incident,"INVALID_CLOCK")

    def test_unrecognized_outcome_is_critical(self):
        state=advance(self.flat(),now=105,sampled_at=104,outcome="TRADE")
        self.assertEqual(state.incident,"INVALID_SAMPLE")
        self.assertFalse(state.may_trade)

if __name__=="__main__":
    unittest.main()
