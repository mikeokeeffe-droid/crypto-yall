"""Synthetic ownership handoff evidence tests. No exchange calls or writes."""
import copy
import unittest
from offline_filled_ownership_review import review_filled_entry_ownership


class OwnershipEvidenceTests(unittest.TestCase):
    def case(self):
        intent=dict(bot="daily", coin="SOL", token="token1", status="uncertain",
                    action="open_long", exchange_order_id="777",
                    submitted_at_ms=100000, requested_size="2")
        order=dict(account="test-account", coin="SOL", order_id="777",
                   side="long", status="filled", final=True, complete=True,
                   filled_size="2")
        baseline=dict(account="test-account", coin="SOL", fresh=True, complete=True,
                      open_orders=[])
        before=dict(baseline, capture_id="before", observed_at_ms=99000, position_size="0")
        fill=dict(account="test-account", coin="SOL", order_id="777",
                  side="long", fill_id="fill1", size="2", time_ms=100500)
        first=dict(baseline, capture_id="first", observed_at_ms=101000,
                   position_size="2", fills_complete=True, fills=[fill])
        second=dict(baseline, capture_id="second", observed_at_ms=102000,
                    position_size="2", fills_complete=True, fills=[fill.copy()])
        return dict(intent=intent, expected_bot="daily", expected_coin="SOL",
                    expected_token="token1", expected_account="test-account",
                    order=order, before=before, first=first, second=second,
                    now_ms=103000)

    def evaluate(self, **changes):
        c=self.case()
        c.update(changes)
        return review_filled_entry_ownership(**c)

    def test_full_fill_is_review_candidate_only(self):
        self.assertEqual(self.evaluate().status, "handoff_candidate")

    def test_untrusted_order_or_intent_blocks(self):
        c=self.case()
        for target, key, value in [
            ("intent","bot","aggressive"), ("intent","status","pending"),
            ("intent","exchange_order_id","wrong"),
            ("intent","action","pyramid_long"), ("intent","requested_size","3"),
            ("order","order_id","wrong"), ("order","account","wrong"),
            ("order","filled_size","1"), ("order","status","canceled"),
            ("order","final",False),
        ]:
            with self.subTest(target=target,key=key):
                x=copy.deepcopy(c)
                x[target][key]=value
                self.assertEqual(review_filled_entry_ownership(**x).status,"hold")

    def test_other_bot_position_or_incomplete_fills_blocks(self):
        c=self.case()
        for target,key,value in [
            ("before","position_size","2"), ("first","position_size","1"),
            ("second","position_size","-2"), ("first","fills_complete",False),
            ("first","fills",[]), ("second","capture_id","first"),
            ("first","observed_at_ms",99999),
            ("second","observed_at_ms",200000),
            ("second","open_orders",[{"coin":"SOL"}]),
        ]:
            with self.subTest(target=target,key=key):
                x=copy.deepcopy(c)
                x[target][key]=value
                self.assertEqual(review_filled_entry_ownership(**x).status,"hold")

    def test_foreign_or_duplicate_fills_block(self):
        c=self.case()
        for f in [
            dict(c["first"]["fills"][0],order_id="other"),
            dict(c["first"]["fills"][0],account="other"),
            dict(c["first"]["fills"][0],size="1"),
        ]:
            x=copy.deepcopy(c)
            x["first"]["fills"]=[f]
            self.assertEqual(review_filled_entry_ownership(**x).status,"hold")
        x=copy.deepcopy(c)
        x["first"]["fills"].append(dict(x["first"]["fills"][0]))
        self.assertEqual(review_filled_entry_ownership(**x).status,"hold")

    def test_short_entry_with_matching_signed_position(self):
        c=self.case()
        c["intent"]["action"]="open_short"
        c["order"]["side"]="short"
        c["first"]["position_size"]="-2"
        c["second"]["position_size"]="-2"
        c["first"]["fills"][0]["side"]="short"
        c["second"]["fills"][0]["side"]="short"
        self.assertEqual(review_filled_entry_ownership(**c).status,"handoff_candidate")


if __name__=="__main__":
    unittest.main()
