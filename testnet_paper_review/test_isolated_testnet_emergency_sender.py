"""Fake-only simulation of hard-disabled TESTNET emergency close transport.

No real exchange connection, no signer file, no public API, and no live order.
"""
from pathlib import Path
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

import hyperliquid.exchange

import testnet_paper_review.emergency_close_one_shot_journal as ej
import testnet_paper_review.isolated_testnet_emergency_sender as es
from testnet_paper_review.single_host_live_journal import SingleHostOneShotJournal
from testnet_paper_review.testnet_emergency_close_review import EmergencyCloseReview
from testnet_paper_review.offline_order_guard import TESTNET_ACCOUNT, TESTNET_ENDPOINT
from testnet_paper_review.testnet_sdk_server_client_preflight import AGENT_ADDRESS


REQUEST="emergency-sol-00001"
ORIGINAL="review-signer-0001"
HASH="a"*64


def plan():
    return EmergencyCloseReview(
        account=TESTNET_ACCOUNT,network="hyperliquid-testnet",
        request_id=ORIGINAL,observed_position_size="0.28",missing_stop=True,
        close_order={
            "coin":"SOL","is_buy":False,"sz":"0.28","limit_px":"68.55",
            "order_type":{"limit":{"tif":"Ioc"}},
            "reduce_only":True,"cloid":"0x"+"b"*32
        }
    )


def approval():
    return es.EmergencyCloseApproval(
        request_id=REQUEST,original_request_id=ORIGINAL,
        plan_hash=HASH,signer=AGENT_ADDRESS,owner=TESTNET_ACCOUNT,
        endpoint=TESTNET_ENDPOINT,observed_position_size="0.28",
        expires_at_s=10010,operator_approved=True
    )


class FakeExchange:
    def __init__(self,result=None):
        self.base_url=TESTNET_ENDPOINT
        self.info=SimpleNamespace(base_url=TESTNET_ENDPOINT)
        self.account_address=TESTNET_ACCOUNT
        self.wallet=SimpleNamespace(address=AGENT_ADDRESS)
        self.vault_address=None
        self.result=result or {
            "status":"ok",
            "response":{"data":{"statuses":[
                {"filled":{"oid":10001,"totalSz":"0.28"}}
            ]}}
        }
        self.calls=[]
    def order(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        if self.result=="timeout":raise TimeoutError("synthetic unknown ack")
        return self.result


class EmergencySenderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="emergency-fake-")
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        os.chmod(root,0o700)
        self.entry_path=str(root/"testnet-one-shot.sqlite3")
        self.emergency_path=str(root/"testnet-emergency-close.sqlite3")
        p=patch.object(ej,"JOURNAL_PATH",self.emergency_path)
        p.start()
        self.addCleanup(p.stop)

    def journals(self):
        entry=SingleHostOneShotJournal(self.entry_path,initialize=True)
        entry.reserve(request_id=ORIGINAL,request_hash=HASH,code_sha="f"*40)
        entry.freeze()
        emergency=ej.EmergencyCloseJournal(initialize=True)
        return entry,emergency

    def fake_run(self,exchange,entry,rescue,*,prop=None,app=None):
        with patch.object(hyperliquid.exchange,"Exchange",FakeExchange), \
             patch.object(es,"ACTIVATION_HOLD",False):
            return es.send_emergency_once(
                exchange=exchange,proposal=prop or plan(),
                approval=app or approval(),entry_journal=entry,
                emergency_journal=rescue,now_s=10000
            )

    def test_hard_lock_makes_real_order_unreachable(self):
        self.assertTrue(es.ACTIVATION_HOLD)
        entry,rescue=self.journals()
        try:
            exchange=FakeExchange()
            with self.assertRaises(es.EmergencySenderHold):
                es.send_emergency_once(
                    exchange=exchange,proposal=plan(),approval=approval(),
                    entry_journal=entry,emergency_journal=rescue,now_s=10000
                )
            self.assertEqual(exchange.calls,[])
            self.assertIsNone(rescue.view())
        finally:
            rescue.close();entry.close()

    def test_fake_one_close_then_never_retry_even_restart(self):
        entry,rescue=self.journals()
        try:
            exchange=FakeExchange()
            receipt=self.fake_run(exchange,entry,rescue)
            self.assertTrue(receipt["needs_independent_zero_position_and_order_check"])
            self.assertFalse(receipt["may_retry"])
            self.assertEqual(len(exchange.calls),1)
            args,kwargs=exchange.calls[0]
            self.assertEqual(args[0],"SOL")
            self.assertFalse(args[1])
            self.assertTrue(kwargs["reduce_only"])
            self.assertEqual(args[4],{"limit":{"tif":"Ioc"}})
            self.assertEqual(rescue.view()[2],"ACK_SEEN")
            with self.assertRaises(es.EmergencySenderHold):
                self.fake_run(exchange,entry,rescue)
            self.assertEqual(len(exchange.calls),1)
        finally:
            rescue.close();entry.close()
        with ej.EmergencyCloseJournal() as after:
            self.assertEqual(after.view()[2],"ACK_SEEN")

    def test_fake_timeout_and_missing_fill_are_permanently_spent(self):
        for result in ("timeout",{"status":"err"},{"status":"ok","response":{"data":{"statuses":[]}}}):
            with self.subTest(result=result):
                # Remove the disposable fixture, NEVER a production journal.
                if Path(self.emergency_path).exists():
                    Path(self.emergency_path).unlink()
                if Path(self.entry_path).exists():
                    Path(self.entry_path).unlink()
                entry,rescue=self.journals()
                try:
                    exchange=FakeExchange(result=result)
                    with self.assertRaises(es.EmergencySenderHold):
                        self.fake_run(exchange,entry,rescue)
                    self.assertEqual(len(exchange.calls),1)
                    self.assertEqual(rescue.view()[2],"UNKNOWN_ACK")
                finally:
                    rescue.close();entry.close()

    def test_bad_owner_not_reduce_only_and_no_original_entry_all_hold(self):
        for change in (
            lambda p,a: (p,es.EmergencyCloseApproval(**{**a.__dict__,"endpoint":"https://api.hyperliquid.xyz"})),
            lambda p,a: (EmergencyCloseReview(**{**p.__dict__,
                "close_order":{**p.close_order,"reduce_only":False}}),a),
            lambda p,a: (EmergencyCloseReview(**{**p.__dict__,
                "close_order":{**p.close_order,"is_buy":True}}),a),
            lambda p,a: (p,es.EmergencyCloseApproval(**{**a.__dict__,"observed_position_size":"0.50"})),
        ):
            entry,rescue=self.journals()
            try:
                prop,app=change(plan(),approval())
                fake=FakeExchange()
                with self.assertRaises(es.EmergencySenderHold):
                    self.fake_run(fake,entry,rescue,prop=prop,app=app)
                self.assertEqual(len(fake.calls),0)
                self.assertIsNone(rescue.view())
            finally:
                rescue.close();entry.close()
            Path(self.entry_path).unlink()
            Path(self.emergency_path).unlink()

if __name__=="__main__":
    unittest.main()
