"""Fake-only SOL Testnet restart recovery tests. No network or signer."""
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
from pathlib import Path
import os

from testnet_paper_review import testnet_restart_public_recovery as recovery
from testnet_paper_review.one_shot_protection_evidence import EvidenceReceipt
from testnet_paper_review.test_offline_signer_boundary import valid
from testnet_paper_review.offline_client_order_bundle import build_offline_client_order_bundle
from testnet_paper_review.testnet_post_ack_public_reconciliation import PostAckPublicReceipt
from testnet_paper_review.offline_order_guard import TESTNET_ACCOUNT, TESTNET_ENDPOINT


def specimen():
    args=valid()
    bundle=build_offline_client_order_bundle(**args)
    result={"status":"ok","response":{"data":{"statuses":[
        {"filled":{"oid":101,"totalSz":bundle.orders[0]["sz"]}},
        {"resting":{"oid":102}},
        {"resting":{"oid":103}}
    ]}}}
    return args["plan"],bundle,result


class EntryJournal:
    def __init__(self,state):self.state=state
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def view(self):return self.state


class Evidence:
    def __init__(self,stored):self.stored=stored
    def read_restart_state(self):return self.stored


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        plan,bundle,response=specimen()
        self.plan=plan
        self.bundle=bundle
        self.response=response
        self.claim=(bundle.request_id,bundle.plan_hash,bundle.code_sha,"RESPONSE_SEEN")
        self.stored=EvidenceReceipt(plan,bundle,response,True)
        self.receipt=PostAckPublicReceipt(
            account=TESTNET_ACCOUNT,network="hyperliquid-testnet",
            position_count=1,open_protection_count=2,entry_oid=101,
            take_profit_oid=102,stop_loss_oid=103
        )
        self.tmp=tempfile.TemporaryDirectory(prefix="testnet-recovery-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        os.chmod(self.root,0o700)

    def evaluate(self,*,state=None,stored=None,public=None,
                 entry_locked=True,rescue_locked=True):
        if state is None:state={"frozen":True,"claim":self.claim}
        if stored is None:stored=self.stored
        if public is None:public=self.receipt
        with patch.object(recovery,"ROOT",str(self.root)):
            return recovery.check_restart_recovery(
                journal_factory=lambda _:EntryJournal(state),
                evidence_factory=lambda:Evidence(stored),
                public_review=lambda **kw: public,
                entry_locked=entry_locked,rescue_locked=rescue_locked
            )

    def test_exact_full_ack_and_independent_pair_still_hold(self):
        x=self.evaluate()
        self.assertTrue(x.bracket_observed)
        self.assertFalse(x.may_send)
        self.assertEqual((x.entry_oid,x.take_profit_oid,x.stop_loss_oid),(101,102,103))
        self.assertIn("STILL_HOLD",x.status)

    def test_no_attempt_with_no_witness_is_only_empty_state(self):
        x=self.evaluate(state={"frozen":False,"claim":None})
        self.assertEqual(x.stage,"NO_ENTRY_ATTEMPT")
        self.assertFalse(x.bracket_observed)
        self.assertFalse(x.may_send)
        (self.root/recovery.PREPARED).write_text("stale")
        with self.assertRaises(recovery.RecoveryHold):
            self.evaluate(state={"frozen":False,"claim":None})

    def test_missing_unknown_ack_and_unfrozen_claim_hold(self):
        cases=[
            {"frozen":True,"claim":None},
            {"frozen":False,"claim":self.claim},
            {"frozen":True,"claim":(*self.claim[:3],"UNKNOWN_ACK")},
            {"frozen":True,"claim":(*self.claim[:3],"RESERVED")},
        ]
        for state in cases:
            with self.subTest(state=state),self.assertRaises(recovery.RecoveryHold):
                self.evaluate(state=state)
        with self.assertRaises(recovery.RecoveryHold):
            self.evaluate(stored=replace(self.stored,ack_present=False,response=None))
        with self.assertRaises(recovery.RecoveryHold):
            self.evaluate(stored=replace(self.stored,may_trade=True))

    def test_changed_request_code_hash_and_account_hold(self):
        for changed in (
            (self.claim[0]+"-other",*self.claim[1:]),
            (self.claim[0],"f"*64,*self.claim[2:]),
            (self.claim[0],self.claim[1],"b"*40,self.claim[3]),
        ):
            with self.subTest(claim=changed),self.assertRaises(recovery.RecoveryHold):
                self.evaluate(state={"frozen":True,"claim":changed})
        with self.assertRaises(recovery.RecoveryHold):
            self.evaluate(stored=replace(
                self.stored,bundle=replace(self.bundle,endpoint="https://api.hyperliquid.xyz")
            ))

    def test_missing_stops_bad_owner_or_unlocked_sender_hold(self):
        for changed in (
            replace(self.receipt,open_protection_count=1),
            replace(self.receipt,position_count=0),
            replace(self.receipt,account="0x"+"0"*40),
        ):
            with self.subTest(changed=changed),self.assertRaises(recovery.RecoveryHold):
                self.evaluate(public=changed)
        with self.assertRaises(recovery.RecoveryHold):
            self.evaluate(entry_locked=False)
        with self.assertRaises(recovery.RecoveryHold):
            self.evaluate(rescue_locked=False)

    def test_observer_failure_fails_closed(self):
        with patch.object(recovery,"ROOT",str(self.root)):
            with self.assertRaises(recovery.RecoveryHold):
                recovery.check_restart_recovery(
                    journal_factory=lambda _:EntryJournal({"frozen":True,"claim":self.claim}),
                    evidence_factory=lambda:Evidence(self.stored),
                    public_review=lambda **kw:(_ for _ in ()).throw(
                        recovery.PostAckPublicHold("missing stop")
                    ),
                    entry_locked=True,rescue_locked=True
                )
        self.assertEqual(recovery.main([]),2)

    def test_no_signers_mutating_or_order_sender_methods(self):
        import ast
        tree=ast.parse(Path(recovery.__file__).read_text())
        imported={x.module for x in ast.walk(tree)
                  if isinstance(x,ast.ImportFrom) and x.module}
        self.assertFalse(any(x.startswith(("hyperliquid.exchange","eth_account"))
                             for x in imported))
        method_names={x.name for x in ast.walk(tree) if isinstance(x,ast.FunctionDef)}
        self.assertFalse({"bulk_orders","send_once","place_order","market_open",
                          "market_close","update_leverage","reserve","freeze"}
                         & method_names)

if __name__=="__main__":
    unittest.main()
