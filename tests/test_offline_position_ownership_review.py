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

    def test_partial_fill_allows_only_review_within_remaining_exposure(self):
        partial=replace(BASE,attributable_remaining="0.4",
                        current_position_size="0.4",requested_close_size="0.25")
        result=review_offline_ownership(partial)
        self.assertEqual(result.state,"review")
        self.assertFalse(result.submit_authorized)
        self.assertEqual(review_offline_ownership(replace(
            partial,requested_close_size="0.5")).state,"hold")

    def test_position_reduction_below_requested_close_holds(self):
        reduced=replace(BASE,attributable_remaining="1.0",
                        current_position_size="0.3",requested_close_size="0.5")
        self.assertEqual(review_offline_ownership(reduced).state,"hold")

    def test_external_position_change_invalidates_ownership_review(self):
        for changes in (
            {"other_bot_activity":True,"current_position_size":"2.5"},
            {"unknown_or_manual_fills":True,"current_position_size":"0.7"},
            {"side_matches":False,"current_position_size":"1.0"},
        ):
            result=review_offline_ownership(replace(BASE,**changes))
            self.assertEqual(result.state,"hold")
            self.assertFalse(result.submit_authorized)

    def test_cancelled_unfilled_order_has_no_attributable_exposure(self):
        cancelled=replace(BASE,attributable_remaining="0",
                          current_position_size="0",requested_close_size="1")
        result=review_offline_ownership(cancelled)
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)

    def test_reversed_position_holds_even_if_quantity_matches(self):
        reversed_position=replace(BASE,side_matches=False,
                                  attributable_remaining="1",
                                  current_position_size="1",
                                  requested_close_size="1")
        result=review_offline_ownership(reversed_position)
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)

    def test_fully_closed_position_cannot_be_closed_again(self):
        fully_closed=replace(BASE,attributable_remaining="0",
                             current_position_size="0",
                             requested_close_size="0.1")
        result=review_offline_ownership(fully_closed)
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)

    def test_no_live_submission_authority_even_for_valid_evidence(self):
        self.assertFalse(review_offline_ownership(BASE).submit_authorized)

if __name__=="__main__":
    unittest.main()
