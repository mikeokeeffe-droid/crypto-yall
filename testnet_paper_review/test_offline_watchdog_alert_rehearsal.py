"""Synthetic emergency delivery tests. No network or notification service."""
import unittest
from dataclasses import replace
from testnet_paper_review.offline_watchdog_policy import WatchdogState,advance
from testnet_paper_review.offline_watchdog_alert_rehearsal import review_delivery

class AlertRehearsalTests(unittest.TestCase):
    def incident(self):
        return advance(WatchdogState(),now=100,sampled_at=99,outcome="MISSING_STOP")

    def assert_hold(self,result):
        self.assertFalse(result.operator_acknowledged)
        self.assertFalse(result.incident_cleared)
        self.assertFalse(result.may_trade)

    def test_primary_ack_is_not_human_ack(self):
        result=review_delivery(self.incident(),primary_result="TRANSPORT_ACK")
        self.assertEqual(result.primary,"TRANSPORT_ACK_NOT_HUMAN_ACK")
        self.assertEqual(result.secondary,"HUMAN_ACK_STILL_REQUIRED")
        self.assert_hold(result)

    def test_backup_delivery_after_primary_failure(self):
        for failure in (None,"FAILED","TIMEOUT"):
            result=review_delivery(self.incident(),primary_result=failure,
                                   secondary_result="TRANSPORT_ACK")
            self.assertEqual(result.primary,"PRIMARY_UNCONFIRMED")
            self.assertEqual(result.secondary,"SECONDARY_TRANSPORT_ACK_NOT_HUMAN_ACK")
            self.assert_hold(result)

    def test_both_channels_fail(self):
        for failure in (None,"FAILED","TIMEOUT"):
            result=review_delivery(self.incident(),primary_result=failure,
                                   secondary_result=failure)
            self.assertEqual(result.secondary,"SECONDARY_UNCONFIRMED_CRITICAL")
            self.assert_hold(result)

    def test_no_incident_does_not_authorize_trading(self):
        state=advance(WatchdogState(),now=100,sampled_at=99,outcome="FLAT")
        result=review_delivery(state)
        self.assertEqual(result.primary,"NO_CRITICAL_INCIDENT")
        self.assert_hold(result)
        result=review_delivery(state,primary_result="TRANSPORT_ACK")
        self.assertEqual(result.primary,"UNEXPECTED_DELIVERY_RESULT")
        self.assert_hold(result)

    def test_inconsistent_delivery_requires_escalation(self):
        result=review_delivery(self.incident(),primary_result="TRANSPORT_ACK",
                               secondary_result="TRANSPORT_ACK")
        self.assertEqual(result.secondary,"INDEPENDENT_ESCALATION_REQUIRED")
        self.assert_hold(result)

    def test_invalid_states_require_escalation(self):
        for state in (None,replace(self.incident(),may_trade=True),
                      replace(self.incident(),severity="HOLD"),
                      WatchdogState(severity="CRITICAL")):
            result=review_delivery(state)
            self.assertEqual(result.primary,"INVALID_STATE_CRITICAL")
            self.assert_hold(result)

    def test_later_flat_read_does_not_clear_incident(self):
        state=advance(self.incident(),now=105,sampled_at=104,outcome="FLAT")
        result=review_delivery(state,primary_result="TRANSPORT_ACK")
        self.assertEqual(state.incident,"MISSING_STOP")
        self.assertEqual(result.secondary,"HUMAN_ACK_STILL_REQUIRED")
        self.assert_hold(result)

if __name__=="__main__":
    unittest.main()
