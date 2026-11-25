"""Offline crash/restart/duplicate protected-bracket lifecycle rehearsal."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from testnet_paper_review.offline_bracket_lifecycle import (
    stage_synthetic_bracket, reconcile_synthetic_bracket
)
from testnet_paper_review.offline_order_guard import (
    SyntheticIntent, TESTNET_ACCOUNT, TESTNET_ENDPOINT, HoldError
)
from testnet_paper_review.offline_durable_restart_journal import (
    DisposableReviewJournal, FILENAME, TMP_PREFIX
)
from testnet_paper_review.test_offline_order_guard import (
    good_snapshot, NOW
)
from testnet_paper_review.test_testnet_daily_admission_gate import fixture
from testnet_paper_review.test_offline_bracket_reconciliation import proof
from testnet_paper_review.offline_daily_bracket_plan import compose_mock_bracket


class OfflineProtectedLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=TMP_PREFIX)
        self.path = Path(self.tmp.name) / FILENAME
        with DisposableReviewJournal(self.path, initialize=True):
            pass
        inputs = fixture()
        inputs.update({"mid_price": "66.40", "notional_usdc": "20"})
        self.plan = compose_mock_bracket(**inputs)
        self.intent = SyntheticIntent(
            request_id="review-bracket-0001",
            account=TESTNET_ACCOUNT,
            endpoint=TESTNET_ENDPOINT,
            symbol="SOL",
            side="buy",
            notional_usdc="20",
            leverage=1,
            expires_at_s=NOW + 30,
        )
        self.snapshot = good_snapshot()
        self.observation = proof()
        self.observation["plan"] = self.plan

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, intent=None, plan=None):
        return stage_synthetic_bracket(
            self.path, intent=intent or self.intent,
            snapshot=self.snapshot, plan=plan or self.plan,
            now_s=NOW,
        )

    def reconcile(self, observation=None):
        values=dict(observation if observation is not None else self.observation)
        # Integration passes plan separately, avoiding duplicate kwargs.
        values.pop("plan", None)
        return reconcile_synthetic_bracket(
            self.path, request_id=self.intent.request_id, plan=self.plan,
            observation=values
        )

    def test_staged_claim_then_restart_persists_and_blocks_competitor(self):
        result=self.stage()
        self.assertEqual(result.state, "STAGED_HOLD")
        self.assertFalse(result.may_send)
        with DisposableReviewJournal(self.path) as j:
            self.assertEqual(j.view()[3], "STAGED_HOLD")
        with self.assertRaises(HoldError):
            self.stage(replace(self.intent, request_id="review-bracket-0002"))
        with DisposableReviewJournal(self.path) as j:
            self.assertEqual(j.view()[0], self.intent.request_id)

    def test_reconciled_bracket_consumed_forever(self):
        self.stage()
        result=self.reconcile()
        self.assertEqual(result.state,"RECONCILED_HOLD")
        self.assertFalse(result.may_send)
        with DisposableReviewJournal(self.path) as j:
            self.assertEqual(j.view()[3],"RECONCILED_HOLD")
            self.assertFalse(j.is_frozen())
        with self.assertRaises(HoldError):
            self.stage(replace(self.intent,request_id="review-bracket-0003"))
        with self.assertRaises(HoldError):
            self.reconcile()

    def test_missing_stop_or_partial_fill_freezes_durably(self):
        for change in ("missing_stop","partial_fill","wrong_reduce_only","wrong_account","missing_ack"):
            with self.subTest(change=change):
                # Fresh disposable directory for each independent mock trial.
                with tempfile.TemporaryDirectory(prefix=TMP_PREFIX) as folder:
                    path=Path(folder)/FILENAME
                    with DisposableReviewJournal(path,initialize=True):
                        pass
                    stage_synthetic_bracket(path,intent=self.intent,
                                            snapshot=self.snapshot,plan=self.plan,now_s=NOW)
                    o=proof()
                    o.pop("plan",None)
                    if change=="missing_stop":
                        o["frontend_open_orders"].pop()
                    elif change=="partial_fill":
                        o["response"]["response"]["data"]["statuses"][0]["filled"]["totalSz"]="0.01"
                    elif change=="wrong_reduce_only":
                        o["frontend_open_orders"][1]["reduceOnly"]=False
                    elif change=="wrong_account":
                        o["account"]="0x"+"0"*40
                    elif change=="missing_ack":
                        o["response"]=None
                    with self.assertRaises(HoldError):
                        reconcile_synthetic_bracket(path,request_id=self.intent.request_id,
                                                    plan=self.plan,observation=o)
                    with DisposableReviewJournal(path) as j:
                        self.assertEqual(j.view()[3],"UNRESOLVED_HOLD")
                        self.assertTrue(j.is_frozen())
                    with self.assertRaises(HoldError):
                        stage_synthetic_bracket(
                            path,intent=replace(self.intent,request_id="review-new-0009"),
                            snapshot=self.snapshot,plan=self.plan,now_s=NOW
                        )

    def test_wrong_intent_size_direction_account_blocks_without_claim(self):
        for candidate in (
            replace(self.intent,side="sell"),
            replace(self.intent,symbol="ETH"),
            replace(self.intent,account="0x"+"0"*40),
            replace(self.intent,notional_usdc="12"),
        ):
            with self.subTest(intent=candidate),self.assertRaises(HoldError):
                self.stage(candidate)
        with DisposableReviewJournal(self.path) as j:
            self.assertIsNone(j.view())

    def test_missing_persistent_file_fails_closed(self):
        self.path.unlink()
        with self.assertRaises(HoldError):
            self.stage()
        self.assertFalse(self.path.exists())

    def test_no_exchange_sdk_or_submit_method(self):
        import ast
        import testnet_paper_review.offline_bracket_lifecycle as module
        tree=ast.parse(Path(module.__file__).read_text())
        imports={node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node,ast.ImportFrom) and node.module}
        imports|={a.name.split(".")[0] for node in ast.walk(tree)
                  if isinstance(node,ast.Import) for a in node.names}
        self.assertFalse({"hyperliquid","eth_account","requests","socket",
                          "http","urllib","subprocess"} & imports)
        names={node.name for node in ast.walk(tree) if isinstance(node,ast.FunctionDef)}
        self.assertFalse({"submit_order","market_open","market_close",
                          "cancel","execute_trade","main"} & names)


if __name__=="__main__":
    unittest.main()
