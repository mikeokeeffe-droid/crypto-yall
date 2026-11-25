"""Offline negative tests: this is NOT a trading executable."""
from dataclasses import replace
import ast
from pathlib import Path
import unittest
from testnet_paper_review.offline_order_guard import (
    HoldError, OfflineOneShotJournal, REVIEW_WRITER, TESTNET_ACCOUNT,
    TESTNET_ENDPOINT, SyntheticIntent, SyntheticSnapshot, inspect_synthetic,
)
NOW = 1700000000

def good_intent():
    return SyntheticIntent("review-unique-0001", TESTNET_ACCOUNT, TESTNET_ENDPOINT,
                           "SOL", "buy", "12.00", 1, NOW + 30)

def good_snapshot():
    return SyntheticSnapshot(TESTNET_ACCOUNT, NOW - 5, "1000.00", 0, ())

class FailClosedReviewTests(unittest.TestCase):
    def check_hold(self, intent=None, snap=None):
        with self.assertRaises(HoldError):
            inspect_synthetic(intent if intent is not None else good_intent(),
                              snap if snap is not None else good_snapshot(), now_s=NOW)

    def test_synthetic_valid_still_holds(self):
        self.assertIn("HOLD", inspect_synthetic(good_intent(), good_snapshot(), now_s=NOW))

    def test_mainnet_or_other_endpoint_rejected(self):
        for x in ("https://api.hyperliquid.xyz", "", None, TESTNET_ENDPOINT+"/"):
            with self.subTest(x=x): self.check_hold(intent=replace(good_intent(),endpoint=x))

    def test_wrong_account_and_live_mode_rejected(self):
        self.check_hold(intent=replace(good_intent(),account="0x"+"0"*40))
        self.check_hold(snap=replace(good_snapshot(),account="0x"+"0"*40))
        self.check_hold(intent=replace(good_intent(),mode="LIVE"))
        self.check_hold(snap=replace(good_snapshot(),mode="LIVE"))

    def test_reject_oversized_unknown_or_expired_intent(self):
        for changes in (
            {"notional_usdc":"11.99"}, {"notional_usdc":"25.01"},
            {"notional_usdc":"nan"}, {"notional_usdc":"1e9"},
            {"notional_usdc":"12.0000001"}, {"notional_usdc":"-1"},
            {"leverage":2}, {"leverage":True},
            {"symbol":"BTC"}, {"side":"close"},
            {"expires_at_s":NOW}, {"expires_at_s":NOW+61},
            {"request_id":""}, {"request_id":"bad/id"},
        ):
            with self.subTest(changes=changes): self.check_hold(intent=replace(good_intent(),**changes))

    def test_reject_stale_balance_or_foreign_positions(self):
        for changes in (
            {"open_order_count":1}, {"open_order_count":True},
            {"position_coins":("SOL",)}, {"position_coins":["SOL"]},
            {"observed_at_s":NOW-16}, {"observed_at_s":NOW+1},
            {"available_usdc":"11.99"}, {"available_usdc":"N/A"},
        ):
            with self.subTest(changes=changes): self.check_hold(snap=replace(good_snapshot(),**changes))

    def test_no_duplicate_or_competing_writer(self):
        j=OfflineOneShotJournal()
        with self.assertRaises(HoldError):
            j.stage(good_intent(),good_snapshot(),now_s=NOW,writer_id="aggressive")
        self.assertEqual(j.state,"EMPTY")
        self.assertIn("HOLD",j.stage(good_intent(),good_snapshot(),now_s=NOW,writer_id=REVIEW_WRITER))
        for intent in (good_intent(),replace(good_intent(),request_id="review-unique-0002")):
            with self.assertRaises(HoldError):
                j.stage(intent,good_snapshot(),now_s=NOW,writer_id=REVIEW_WRITER)
        self.assertEqual(j.orders_attempted,0)

    def test_unknown_ack_never_retries(self):
        j=OfflineOneShotJournal()
        j.stage(good_intent(),good_snapshot(),now_s=NOW,writer_id=REVIEW_WRITER)
        j.simulate_ack(good_intent().request_id,"unknown")
        self.assertEqual(j.state,"UNKNOWN_ACK_HOLD")
        with self.assertRaises(HoldError):
            j.stage(replace(good_intent(),request_id="review-unique-0002"),
                    good_snapshot(),now_s=NOW,writer_id=REVIEW_WRITER)
        with self.assertRaises(HoldError):
            j.simulate_ack(good_intent().request_id,"filled")
        self.assertEqual(j.orders_attempted,0)

    def test_stale_reconciliation_is_permanent_hold(self):
        j=OfflineOneShotJournal()
        j.stage(good_intent(),good_snapshot(),now_s=NOW,writer_id=REVIEW_WRITER)
        j.simulate_ack(good_intent().request_id,"unknown")
        j.reconcile_fixture(good_intent().request_id,fresh_evidence=False,exact_match=True)
        self.assertEqual(j.state,"UNRESOLVED_HOLD")
        with self.assertRaises(HoldError):
            j.reconcile_fixture(good_intent().request_id,fresh_evidence=True,exact_match=True)
        self.assertEqual(j.orders_attempted,0)

    def test_reconciled_fixture_cannot_reset(self):
        j=OfflineOneShotJournal()
        j.stage(good_intent(),good_snapshot(),now_s=NOW,writer_id=REVIEW_WRITER)
        j.simulate_ack(good_intent().request_id,"filled")
        self.assertIn("HOLD",j.reconcile_fixture(good_intent().request_id,fresh_evidence=True,exact_match=True))
        self.assertEqual(j.state,"RECONCILED_HOLD")
        with self.assertRaises(HoldError):
            j.stage(replace(good_intent(),request_id="review-unique-0002"),
                    good_snapshot(),now_s=NOW,writer_id=REVIEW_WRITER)
        self.assertEqual(j.orders_attempted,0)

    def test_no_network_library_or_submit_entrypoint(self):
        import testnet_paper_review.offline_order_guard as mod
        tree=ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        imports={n.module.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n,ast.ImportFrom) and n.module}
        imports|={a.name.split(".")[0] for n in ast.walk(tree)
                  if isinstance(n,ast.Import) for a in n.names}
        self.assertTrue(imports.isdisjoint({"hyperliquid","requests","urllib","socket","os","subprocess","eth_account"}))
        names={n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
        self.assertTrue(names.isdisjoint({"submit_order","place_order","market_open","market_close","main"}))

if __name__=="__main__":
    unittest.main()
