"""Offline receipt-to-watchdog integration, using synthetic read-only receipts."""
from dataclasses import replace
import unittest
from testnet_paper_review.offline_order_guard import TESTNET_ACCOUNT
from testnet_paper_review.testnet_readonly_emergency_watch import ExposureWatchResult
from testnet_paper_review.offline_watchdog_policy import WatchdogState
from testnet_paper_review.offline_watchdog_receipt_bridge import classify,rehearse_tick

def flat():
    return ExposureWatchResult(
        account=TESTNET_ACCOUNT,coin="SOL",position_count=0,open_order_count=0,
        stage="NO_ATTEMPT",observed_bracket=False,needs_operator=False,
        action="NO_POSITION_NO_ORDER_TRADING_DISABLED")

class ReceiptBridgeTests(unittest.TestCase):
    def test_flat_and_consumed_flat_remain_hold(self):
        for stage in ("NO_ATTEMPT","ENTRY_CONSUMED_BUT_FLAT"):
            state,alert=rehearse_tick(WatchdogState(),now=100,sampled_at=99,
                                      receipt=replace(flat(),stage=stage))
            self.assertIsNone(state.incident)
            self.assertFalse(state.may_trade)
            self.assertEqual(alert,"HOLD_NO_TRADING_AUTHORITY")

    def test_exact_bracket_only_attention(self):
        receipt=replace(flat(),stage="BRACKET_MATCHED_ONE_OBSERVATION",
                        position_count=1,open_order_count=2,
                        observed_bracket=True,needs_operator=True)
        state,alert=rehearse_tick(WatchdogState(),now=100,sampled_at=99,receipt=receipt)
        self.assertEqual(state.severity,"ATTENTION")
        self.assertEqual(alert,"CONTINUE_MONITORING_NO_STOP_GUARANTEE")
        self.assertFalse(state.may_trade)
        self.assertEqual(classify(replace(receipt,open_order_count=1)),"UNVERIFIED")

    def test_alerts_latch_after_flat(self):
        for stage,incident in (
            ("UNOWNED_EXPOSURE","FOREIGN_EXPOSURE"),
            ("UNKNOWN_ACK_OR_UNRESOLVED_ENTRY","UNKNOWN_ACK"),
            ("UNVERIFIED_PROTECTIVE_ORDERS","UNVERIFIED"),
            ("EMERGENCY_ATTEMPT_REQUIRES_REVIEW","EMERGENCY_ATTEMPT"),
        ):
            with self.subTest(stage=stage):
                state,alert=rehearse_tick(WatchdogState(),now=100,sampled_at=99,
                    receipt=replace(flat(),stage=stage,needs_operator=True))
                self.assertEqual(state.incident,incident)
                state,alert=rehearse_tick(state,now=105,sampled_at=104,receipt=flat())
                self.assertEqual(state.incident,incident)
                self.assertEqual(alert,"CRITICAL_OPERATOR_INSPECTION_NO_RETRY")

    def test_bad_receipts_fail_closed(self):
        for receipt in ({},replace(flat(),account="foreign"),
                        replace(flat(),coin="BTC"),replace(flat(),may_trade=True),
                        replace(flat(),may_close=True),replace(flat(),position_count=True),
                        replace(flat(),position_count=1),replace(flat(),open_order_count=-1),
                        replace(flat(),observed_bracket=True),replace(flat(),needs_operator=True),
                        replace(flat(),stage="UNKNOWN",needs_operator=True)):
            with self.subTest(receipt=receipt):
                self.assertEqual(classify(receipt),"UNVERIFIED")
                state,alert=rehearse_tick(WatchdogState(),now=100,sampled_at=99,receipt=receipt)
                self.assertEqual(state.severity,"CRITICAL")
                self.assertFalse(state.may_trade)

    def test_missing_and_replayed_receipts(self):
        state,alert=rehearse_tick(WatchdogState(),now=100,sampled_at=99,receipt=None)
        self.assertEqual(state.incident,"READ_FAILED")
        state,_=rehearse_tick(WatchdogState(),now=100,sampled_at=99,receipt=flat())
        state,alert=rehearse_tick(state,now=101,sampled_at=99,receipt=flat())
        self.assertEqual(state.incident,"STALE_OR_REPLAYED_OBSERVATION")
        self.assertEqual(alert,"CRITICAL_OPERATOR_INSPECTION_NO_RETRY")

if __name__=="__main__":
    unittest.main()
