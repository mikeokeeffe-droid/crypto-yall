"""Offline binding tests: candidate review is never permission to release."""
import unittest
from entry_reconciliation_review_offline import review_persisted_entry_no_fill

class PersistedIntentReviewTests(unittest.TestCase):
    def case(self):
        intent=dict(bot="daily",coin="SOL",token="claim-1",status="uncertain",
                    exchange_order_id="12345",submitted_at_ms=1000,requested_size=0.2)
        order=dict(coin="SOL",order_id="12345",final=True,status="rejected",
                   complete=True,filled_size=0)
        a=dict(account="0xaccount1",capture_id="capture-1",coin="SOL",fresh=True,complete=True,fills_complete=True,
               observed_at_ms=2000,position_size=0,open_orders=[],fills=[])
        b=dict(a,observed_at_ms=3000,capture_id="capture-2")
        return dict(intent=intent,expected_bot="daily",expected_coin="SOL",
                    expected_token="claim-1",expected_account="0xaccount1",order=order,first=a,second=b)

    def test_candidate_requires_bound_identity_and_order(self):
        valid=self.case()
        self.assertEqual(review_persisted_entry_no_fill(**valid).status,"review_candidate")
        for field,value in (("bot","intraday"),("coin","BTC"),("token","other"),
                            ("status","filled"),("status","pending"),
                            ("exchange_order_id",None),("submitted_at_ms",None),
                            ("requested_size",0),("requested_size",float("nan"))):
            with self.subTest(field=field,value=value):
                changed=dict(valid,intent=dict(valid["intent"],**{field:value}))
                self.assertEqual(review_persisted_entry_no_fill(**changed).status,"hold")
        for changes in ({"expected_bot":"aggressive"},{"expected_token":"different"},
                        {"expected_coin":"BTC"},{"order":None}):
            with self.subTest(changes=changes):
                self.assertEqual(review_persisted_entry_no_fill(**dict(valid,**changes)).status,"hold")

    def test_cross_account_or_reused_capture_is_held(self):
        case=self.case()
        variations=(
            {"expected_account":"0xwrong"},
            {"expected_account":""},
            {"order":dict(case["order"],account="0xwrong")},
            {"first":dict(case["first"],account="0xwrong")},
            {"second":dict(case["second"],account="0xwrong")},
            {"second":dict(case["second"],capture_id="capture-1")},
            {"second":dict(case["second"],capture_id=None)},
        )
        for changed in variations:
            with self.subTest(changed=changed):
                self.assertEqual(review_persisted_entry_no_fill(**dict(case,**changed)).status,"hold")

    def test_unknown_orderless_timeout_cannot_be_reviewed_as_final_rejection(self):
        c=self.case()
        c["intent"]=dict(c["intent"],exchange_order_id=None,status="uncertain")
        self.assertEqual(review_persisted_entry_no_fill(**c).status,"hold")

if __name__=="__main__":
    unittest.main()
