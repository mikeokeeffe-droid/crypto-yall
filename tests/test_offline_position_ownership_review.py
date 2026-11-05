"""Synthetic exchange evidence review tests; no order capability."""
import unittest
from dataclasses import replace
from offline_position_ownership_review import (
    OfflineOwnershipEvidence,review_offline_ownership)

BASE=OfflineOwnershipEvidence(
    authenticated_bot="daily",claim_bot="daily",
    account_matches=True,coin_matches=True,side_matches=True,
    history_complete=True,history_fresh=True,fills_attributable=True,
    unknown_or_manual_fills=False,other_bot_activity=False,
    attributable_remaining="1.5",current_position_size="2.0",
    requested_close_size="1.0")

class OwnershipReviewTests(unittest.TestCase):
    def test_consistent_synthetic_evidence_is_review_only(self):
        result=review_offline_ownership(BASE)
        self.assertEqual(result.state,"review")
        self.assertFalse(result.submit_authorized)

    def test_other_bot_and_unknown_identity_hold(self):
        for changes in (
            {"authenticated_bot":"intraday"},
            {"authenticated_bot":"unknown"},
        ):
            self.assertEqual(review_offline_ownership(
                replace(BASE,**changes)).state,"hold")

    def test_missing_or_mismatched_provenance_holds(self):
        for field in ("account_matches","coin_matches","side_matches",
                      "history_complete","history_fresh","fills_attributable"):
            self.assertEqual(review_offline_ownership(
                replace(BASE,**{field:False})).state,"hold")

    def test_manual_or_other_bot_activity_holds(self):
        for field in ("unknown_or_manual_fills","other_bot_activity"):
            self.assertEqual(review_offline_ownership(
                replace(BASE,**{field:True})).state,"hold")

    def test_oversized_close_holds(self):
        for changes in (
            {"requested_close_size":"1.6"},
            {"current_position_size":"0.5"},
            {"attributable_remaining":"0.5"},
        ):
            self.assertEqual(review_offline_ownership(
                replace(BASE,**changes)).state,"hold")

    def test_invalid_quantities_hold(self):
        for value in ("0","-1","NaN","Infinity","not-a-number"):
            self.assertEqual(review_offline_ownership(
                replace(BASE,requested_close_size=value)).state,"hold")

    def test_no_live_submission_authority_even_for_valid_evidence(self):
        self.assertFalse(review_offline_ownership(BASE).submit_authorized)

if __name__=="__main__":
    unittest.main()
