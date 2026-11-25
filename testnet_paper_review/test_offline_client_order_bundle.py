import unittest
from dataclasses import replace
from testnet_paper_review.offline_client_order_bundle import build_offline_client_order_bundle, BracketHold
from testnet_paper_review.test_offline_signer_boundary import valid

class ClientIDsTests(unittest.TestCase):
    def test_three_distinct_stable_ids_no_send(self):
        args=valid()
        a=build_offline_client_order_bundle(**args)
        self.assertEqual(a,build_offline_client_order_bundle(**args))
        self.assertFalse(a.permits_submission)
        self.assertEqual(a.grouping,"normalTpsl")
        self.assertEqual(len({x["cloid"] for x in a.orders}),3)
        self.assertTrue(all(len(x["cloid"])==34 for x in a.orders))
        self.assertEqual([o["reduce_only"] for o in a.orders],[False,True,True])
    def test_identity_renewal_changes_ids(self):
        args=valid()
        a=build_offline_client_order_bundle(**args)
        b=build_offline_client_order_bundle(**{**args,
            "intent":replace(args["intent"],request_id="review-signer-0002")})
        self.assertTrue(set(x["cloid"] for x in a.orders).isdisjoint(
            x["cloid"] for x in b.orders))
    def test_bad_endpoint_and_missing_stop_hold(self):
        args=valid()
        for changed in (
            {"intent":replace(args["intent"],endpoint="https://api.hyperliquid.xyz")},
            {"plan":replace(args["plan"],orders=args["plan"].orders[:2])},
            {"code_sha":"main"},
        ):
            with self.subTest(changed=changed),self.assertRaises(BracketHold):
                build_offline_client_order_bundle(**{**args,**changed})
