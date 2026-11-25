"""Full sender path rehearsal with a FAKE Exchange + real local one-shot journal.

CI installs the public SDK for pure order serialization only. The test patches
the Exchange CLASS to an in-memory fake and patches the source activation HOLD
inside the test scope. No HTTP, signing wallet, account secrets, trade endpoint,
production persistent file, original bot workflow or exchange funds are used.
The in-source ACTIVATION_HOLD remains True outside the test's patch scope.
"""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import hyperliquid.exchange
from testnet_paper_review.isolated_testnet_sender import SenderHold, send_once
from testnet_paper_review.single_host_live_journal import (
    SingleHostOneShotJournal, PersistentHold
)
from testnet_paper_review.test_isolated_testnet_sender import sample
from testnet_paper_review.offline_order_guard import TESTNET_ENDPOINT, TESTNET_ACCOUNT


class FakeExchange:
    def __init__(self, bundle, approval, outcome="full", *, host=TESTNET_ENDPOINT,
                 owner=TESTNET_ACCOUNT, signer=None):
        self.base_url=host
        self.info=SimpleNamespace(base_url=host)
        self.account_address=owner
        self.wallet=SimpleNamespace(address=signer or approval.signer_address)
        self.bundle=bundle
        self.outcome=outcome
        self.calls=[]
    def bulk_orders(self, orders, *, grouping):
        self.calls.append((orders,grouping))
        if self.outcome == "timeout":
            raise TimeoutError("synthetic unknown acknowledgement")
        if self.outcome == "rejected":
            return {"status":"err","response":"fake rejection"}
        size=self.bundle.orders[0]["sz"]
        statuses=[
            {"filled":{"oid":101,"totalSz":size}},
            {"resting":{"oid":102}},
            {"resting":{"oid":103}},
        ]
        if self.outcome == "no_stop":statuses.pop()
        if self.outcome == "partial":statuses[0]["filled"]["totalSz"]="0.001"
        return {"status":"ok","response":{"data":{"statuses":statuses}}}


class FullFakeSenderPathTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="fake-testnet-sender-")
        self.root=Path(self.temp.name)
        os.chmod(self.root,0o700)
        self.path=self.root/"testnet-one-shot.sqlite3"
        self.bundle,self.approval,self.now_s=sample()

    def tearDown(self):
        self.temp.cleanup()

    def exercise_fake(self, journal, fake):
        # Both patches have scope only to this one test invocation.
        # Absolutely no real Exchange object can enter the order sender.
        with patch.object(hyperliquid.exchange,"Exchange",FakeExchange), \
                patch("testnet_paper_review.isolated_testnet_sender.ACTIVATION_HOLD",False):
            return send_once(
                exchange=fake,journal=journal,bundle=self.bundle,
                approval=self.approval,now_s=self.now_s
            )

    def test_success_requires_one_group_and_immutable_journal_claim(self):
        fake=FakeExchange(self.bundle,self.approval)
        with SingleHostOneShotJournal(self.path,initialize=True) as journal:
            result=self.exercise_fake(journal,fake)
            self.assertEqual(result["status"],"POST_ACK_HOLD_NO_MORE_ORDERS")
            self.assertTrue(result["needs_independent_position_stop_reconciliation"])
            self.assertEqual(len(fake.calls),1)
            orders,grouping=fake.calls[0]
            self.assertEqual(grouping,"normalTpsl")
            self.assertEqual(len(orders),3)
            self.assertEqual([o["reduce_only"] for o in orders],[False,True,True])
            self.assertEqual(journal.view()["claim"][3],"RESPONSE_SEEN")
            self.assertTrue(journal.view()["frozen"])
            with self.assertRaises(SenderHold):
                self.exercise_fake(journal,fake)
            self.assertEqual(len(fake.calls),1)
        with SingleHostOneShotJournal(self.path) as journal:
            self.assertTrue(journal.view()["frozen"])
            self.assertEqual(journal.view()["claim"][0],self.approval.request_id)

    def test_timeout_partial_stop_missing_and_rejection_all_freeze_forever(self):
        for outcome in ("timeout","partial","no_stop","rejected"):
            with self.subTest(outcome=outcome):
                # Each synthetic scenario has an independent 0700 directory.
                with tempfile.TemporaryDirectory(prefix="fake-testnet-sender-") as root:
                    os.chmod(root,0o700)
                    path=Path(root)/"testnet-one-shot.sqlite3"
                    fake=FakeExchange(self.bundle,self.approval,outcome=outcome)
                    with SingleHostOneShotJournal(path,initialize=True) as journal:
                        with self.assertRaises(SenderHold):
                            self.exercise_fake(journal,fake)
                        self.assertEqual(len(fake.calls),1)
                        self.assertTrue(journal.view()["frozen"])
                        self.assertEqual(journal.view()["claim"][3],"UNKNOWN_ACK")
                        with self.assertRaises(SenderHold):
                            self.exercise_fake(journal,fake)
                        self.assertEqual(len(fake.calls),1)
                    with SingleHostOneShotJournal(path) as journal:
                        self.assertTrue(journal.view()["frozen"])
                        self.assertEqual(journal.view()["claim"][3],"UNKNOWN_ACK")

    def test_mainnet_mismatched_owner_or_signer_sends_nothing(self):
        variants=(
            {"host":"https://api.hyperliquid.xyz"},
            {"owner":"0x"+"0"*40},
            {"signer":"0x"+"1"*40},
        )
        for change in variants:
            with self.subTest(change=change):
                fake=FakeExchange(self.bundle,self.approval,**change)
                with SingleHostOneShotJournal(self.path,initialize=True) as journal:
                    with self.assertRaises(SenderHold):
                        self.exercise_fake(journal,fake)
                    self.assertEqual(len(fake.calls),0)
                    self.assertIsNone(journal.view()["claim"])
                self.path.unlink()

    def test_hard_activation_hold_remains_true_outside_the_rehearsal(self):
        import testnet_paper_review.isolated_testnet_sender as sender
        self.assertIs(sender.ACTIVATION_HOLD,True)
        fake=FakeExchange(self.bundle,self.approval)
        with SingleHostOneShotJournal(self.path,initialize=True) as journal:
            with self.assertRaises(SenderHold):
                send_once(exchange=fake,journal=journal,bundle=self.bundle,
                          approval=self.approval,now_s=self.now_s)
            self.assertEqual(len(fake.calls),0)
            self.assertIsNone(journal.view()["claim"])


if __name__=="__main__":
    unittest.main()
