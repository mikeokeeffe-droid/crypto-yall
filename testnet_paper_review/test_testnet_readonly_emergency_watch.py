"""Fake-only read-only Testnet exposure watch tests. No exchange/signers."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from testnet_paper_review import testnet_readonly_emergency_watch as watch
from testnet_paper_review.test_offline_bracket_reconciliation import proof
from testnet_paper_review.one_shot_protection_evidence import EvidenceReceipt
from testnet_paper_review.test_offline_signer_boundary import valid
from testnet_paper_review.offline_client_order_bundle import build_offline_client_order_bundle


class FakeReader:
    def __init__(self, case,*, fail=False):
        self.case=case
        self.fail=fail
        self.calls=[]
    def __call__(self,kind):
        self.calls.append(kind)
        if self.fail:raise TimeoutError("synthetic API timeout")
        if kind=="clearinghouseState":
            return {"assetPositions":deepcopy(self.case["positions"])}
        if kind=="openOrders":return deepcopy(self.case["open_orders"])
        if kind=="frontendOpenOrders":return deepcopy(self.case["frontend_open_orders"])
        raise AssertionError("unexpected public read")


class Journal:
    def __init__(self,state):self.state=state
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def view(self):return self.state


class Evidence:
    def __init__(self,record):self.record=record
    def read_restart_state(self):return self.record


class EmergencyWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="emergency-watch-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        args=valid()
        self.plan=args["plan"]
        self.bundle=build_offline_client_order_bundle(**args)
        self.record=EvidenceReceipt(
            plan=self.plan,bundle=self.bundle,
            response={"status":"ok","response":{"data":{"statuses":[
                {"filled":{"oid":101,"totalSz":self.bundle.orders[0]["sz"]}},
                {"resting":{"oid":102}},{"resting":{"oid":103}}
            ]}}},
            ack_present=True
        )
        self.claim=(self.bundle.request_id,self.bundle.plan_hash,
                    self.bundle.code_sha,"RESPONSE_SEEN")

    def check(self,*,case=None,state=None,record=None,reader=None,rescue_claim=None,
              emergency_factory=None):
        data=case if case is not None else {
            "positions":[],"open_orders":[],"frontend_open_orders":[]
        }
        if state is None:state={"frozen":False,"claim":None}
        if reader is None:reader=FakeReader(data)
        if emergency_factory is None:
            def emergency_factory(path,*,read_only):
                self.assertEqual(path,watch.RESCUE_PATH)
                self.assertIs(read_only,True)
                return Journal(rescue_claim)
        return watch.inspect_one_shot_exposure(
            reader=reader,
            emergency_factory=emergency_factory,
            journal_factory=lambda _,*,read_only:Journal(state) if read_only is True else self.fail("entry journal must be read only"),
            evidence_factory=lambda:Evidence(record or self.record),
            clock=lambda:123456,
            evidence_root=str(self.root)
        ),reader

    def test_flat_unused_journal_holds_without_alert(self):
        got,reader=self.check()
        self.assertEqual(got.stage,"NO_ATTEMPT")
        self.assertFalse(got.needs_operator)
        self.assertFalse(got.may_close)
        self.assertFalse(got.may_trade)
        self.assertEqual(len(reader.calls),6)
        self.assertEqual(watch.main([]),2)

    def test_foreign_manual_position_or_order_alerts(self):
        for case in (
            {"positions":[{"position":{"coin":"SOL","szi":"0.4"}}],
             "open_orders":[],"frontend_open_orders":[]},
            {"positions":[],"open_orders":[{"oid":987,"coin":"SOL","side":"A",
              "sz":"0.2"}],"frontend_open_orders":[{"oid":987,"coin":"SOL",
              "side":"A","sz":"0.2","reduceOnly":False,
              "isTrigger":False,"orderType":"Limit","triggerPx":"0"}]},
        ):
            with self.subTest(case=case):
                got,_=self.check(case=case)
                self.assertTrue(got.needs_operator)
                self.assertEqual(got.stage,"UNOWNED_EXPOSURE")

    def test_consumed_emergency_claim_is_urgent_even_when_flat(self):
        for status in ("RESERVED","UNKNOWN_ACK","ACK_SEEN"):
            with self.subTest(status=status):
                got,_=self.check(rescue_claim=("rescue-123","a"*64,status))
                self.assertTrue(got.needs_operator)
                self.assertFalse(got.may_trade)
                self.assertFalse(got.may_close)
                self.assertEqual(got.stage,"EMERGENCY_ATTEMPT_REQUIRES_REVIEW")

    def test_missing_emergency_journal_never_reports_safe_flat(self):
        def missing(*args,**kwargs):
            raise watch.EmergencyJournalHold("synthetic missing rescue journal")
        with self.assertRaises(watch.ExposureWatchHold):
            self.check(emergency_factory=missing)

    def test_unknown_ack_is_urgent_even_when_flat(self):
        for stage in ("UNKNOWN_ACK","RESERVED","FROZEN"):
            with self.subTest(stage=stage):
                state={"frozen":True,"claim":(*self.claim[:3],stage)}
                got,_=self.check(state=state)
                self.assertTrue(got.needs_operator)
                self.assertEqual(got.stage,"UNKNOWN_ACK_OR_UNRESOLVED_ENTRY")

    def test_saved_full_bracket_still_requires_attention(self):
        case=proof()
        got,_=self.check(case=case,state={"frozen":True,"claim":self.claim})
        # The fixture order IDs, stops, and triggers are checked by the
        # reviewed existing bracket observation validator.
        self.assertTrue(got.needs_operator)
        self.assertFalse(got.may_trade)
        self.assertIn(got.stage,("BRACKET_MATCHED_ONE_OBSERVATION",
                                 "UNVERIFIED_PROTECTIVE_ORDERS"))

    def test_missing_stop_requires_human_and_never_automatically_closes(self):
        case=proof()
        case["open_orders"].pop()
        case["frontend_open_orders"].pop()
        got,_=self.check(case=case,state={"frozen":True,"claim":self.claim})
        self.assertTrue(got.needs_operator)
        self.assertFalse(got.may_close)
        self.assertEqual(got.stage,"UNVERIFIED_PROTECTIVE_ORDERS")

    def test_unmatched_and_missing_disk_evidence_hold(self):
        state={"frozen":True,"claim":self.claim}
        with self.assertRaises(watch.ExposureWatchHold):
            self.check(state=state,record=replace(self.record,ack_present=False))
        with self.assertRaises(watch.ExposureWatchHold):
            self.check(state=state,record=replace(self.record,bundle=replace(
                self.bundle,request_id="mismatched-id")))
        (self.root/watch.PREPARED).write_text("stale")
        with self.assertRaises(watch.ExposureWatchHold):
            self.check()

    def test_timeout_and_inconsistent_public_views_hold(self):
        with self.assertRaises(watch.ExposureWatchHold):
            self.check(reader=FakeReader({
                "positions":[],"open_orders":[],"frontend_open_orders":[]
            },fail=True))
        case={"positions":[],"open_orders":[{"oid":2,"coin":"SOL","sz":"1","side":"A"}],
              "frontend_open_orders":[]}
        with self.assertRaises(watch.ExposureWatchHold):
            self.check(case=case)

    def test_no_signers_executors_or_submission_surface(self):
        import ast
        tree=ast.parse(Path(watch.__file__).read_text())
        imported={n.module for n in ast.walk(tree)
                  if isinstance(n,ast.ImportFrom) and n.module}
        self.assertFalse(any(x.startswith(("hyperliquid.exchange","eth_account",
                             "testnet_paper_review.isolated_testnet_sender")) for x in imported))
        method_names={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertFalse({"bulk_orders","send_once","place_order","market_open",
                          "market_close","update_leverage","reserve","freeze"}
                          & method_names)

if __name__=="__main__":
    unittest.main()
