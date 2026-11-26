"""No-network release checkpoint regressions; no wallet files or orders."""
import json
from types import SimpleNamespace
import unittest

from testnet_paper_review.testnet_trial_release_checkpoint import (
    ReleaseGateHold,fetch_sol_leverage,review_release_checkpoint,main
)
from testnet_paper_review.offline_order_guard import TESTNET_ACCOUNT, TESTNET_ENDPOINT


class Journal:
    def __init__(self, path=None, state=None):
        self.state=state
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def view(self):return self.state


def good_preview():
    return SimpleNamespace(
        may_send=False,account=TESTNET_ACCOUNT,endpoint=TESTNET_ENDPOINT,
        journal_empty=True,position_count=0,open_order_count=0
    )


def run(*, preview=None, leverage=None, entry=None, rescue=None,
        entry_hold=True, emergency_hold=True):
    return review_release_checkpoint(
        preview_reader=lambda:preview if preview is not None else good_preview(),
        leverage_reader=lambda:leverage if leverage is not None else {
            "leverage":{"type":"isolated","value":1}
        },
        entry_journal_factory=lambda path:Journal(path,entry if entry is not None else {
            "frozen":False,"claim":None
        }),
        emergency_journal_factory=lambda:Journal(state=rescue),
        entry_sender_held=entry_hold,emergency_sender_held=emergency_hold
    )


class ReleaseCheckpointTests(unittest.TestCase):
    def test_strictly_hold_even_when_all_preflight_inputs_pass(self):
        result=run()
        self.assertFalse(result.may_trade)
        self.assertFalse(result.emergency_live_recovery_proven)
        self.assertFalse(result.exact_daily_signal_confirmed)
        self.assertFalse(result.independent_review_signed_off)
        self.assertTrue(result.entry_journal_unspent)
        self.assertTrue(result.emergency_journal_unspent)
        self.assertEqual(result.leverage,1)
        self.assertEqual(main([]),2)

    def test_2x_cross_and_unknown_leverage_holds(self):
        for value in ({"type":"isolated","value":2},
                      {"type":"cross","value":1},
                      {"type":"isolated","value":"1"},
                      {},None):
            with self.subTest(value=value),self.assertRaises(ReleaseGateHold):
                run(leverage={"leverage":value})

    def test_consumed_rescue_entry_or_unlocked_sender_holds(self):
        for kwargs in (
            {"entry":{"frozen":True,"claim":None}},
            {"entry":{"frozen":False,"claim":("already",)}},
            {"rescue":("rescue", "a"*64,"UNKNOWN_ACK")},
            {"entry_hold":False},
            {"emergency_hold":False},
            {"preview":SimpleNamespace(**{**vars(good_preview()),"position_count":1})},
            {"preview":SimpleNamespace(**{**vars(good_preview()),"may_send":True})},
        ):
            with self.subTest(kwargs=kwargs),self.assertRaises(ReleaseGateHold):
                run(**kwargs)

    def test_live_request_is_only_public_testnet_info(self):
        class FakeResponse:
            status=200
            def getheader(self,k):return None
            def read(self,n):
                return b'{"leverage":{"type":"isolated","value":1}}'
        class FakeHTTPS:
            def __init__(self):self.actions=[]
            def request(self,method,path,body,headers):
                self.actions.append((method,path,json.loads(body)))
            def getresponse(self):return FakeResponse()
            def close(self):pass
        connection=FakeHTTPS()
        result=fetch_sol_leverage(connection_factory=lambda:connection)
        self.assertEqual(result["leverage"]["value"],1)
        self.assertEqual(connection.actions,[("POST","/info",{
            "type":"activeAssetData","user":TESTNET_ACCOUNT,"coin":"SOL"
        })])

if __name__=="__main__":
    unittest.main()
