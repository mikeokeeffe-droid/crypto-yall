"""Fault-injection tests for journal-before-fake ordering, never real orders."""
import concurrent.futures
import os
import tempfile
import unittest
from offline_sender_restart_journal import OfflineRestartJournal
from offline_shared_sender_prototype import FakeExchange
from offline_journaled_fake_dispatch import simulate_journaled_once

SCOPE = dict(environment="mainnet",account="0x"+"1"*40,dex="",coin="SOL")

class JournaledFakeDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=os.path.join(self.tmp.name,"fake.sqlite")
        self.journal=OfflineRestartJournal(self.path)
        self.token,self.cloid,self.fence=self.journal.reserve(bot="daily",**SCOPE)
    def tearDown(self):
        self.tmp.cleanup()
    def attempt(self,fake,**overrides):
        kwargs=dict(journal=self.journal,fake=fake,token=self.token,
                    fence=self.fence,**SCOPE)
        kwargs.update(overrides)
        return simulate_journaled_once(**kwargs)

    def test_marker_is_durable_before_fake_observes(self):
        journal=self.journal
        class ObservingFake(FakeExchange):
            def record_fake_attempt(self,token,cloid):
                self_observation=journal.inspect(**SCOPE)
                assert self_observation[4]=="dispatch_unknown"
                assert self_observation[2]==cloid
                return super().record_fake_attempt(token,cloid)
        # The bridge deliberately accepts only the exact fake type.
        fake=FakeExchange()
        self.assertEqual(self.attempt(fake).state,"observed_unverified")
        self.assertEqual(self.journal.inspect(**SCOPE)[4],"dispatch_unknown")
        self.assertFalse(self.attempt(fake).submit_authorized)

    def test_restart_after_fake_acceptance_cannot_repeat(self):
        fake=FakeExchange()
        self.attempt(fake)
        self.journal=OfflineRestartJournal(self.path)
        self.assertEqual(self.attempt(fake).state,"hold")
        self.assertEqual(len(fake.attempts),1)

    def test_restart_after_lost_response_cannot_repeat(self):
        fake=FakeExchange()
        def lost_reply(token,cloid):
            fake.attempts.append((token,cloid))
            raise TimeoutError("synthetic reply lost")
        fake.record_fake_attempt=lost_reply
        self.assertEqual(self.attempt(fake).state,"hold")
        self.journal=OfflineRestartJournal(self.path)
        self.assertEqual(self.attempt(fake).state,"hold")
        self.assertEqual(len(fake.attempts),1)
        self.assertIsNone(self.journal.reserve(bot="intraday",**SCOPE))

    def test_crash_after_marker_before_fake_stays_locked(self):
        self.assertTrue(self.journal.mark_dispatch_unknown(
            token=self.token,fence=self.fence,**SCOPE))
        fake=FakeExchange()
        self.journal=OfflineRestartJournal(self.path)
        self.assertEqual(self.attempt(fake).state,"hold")
        self.assertEqual(fake.attempts,[])

    def test_parallel_fake_dispatch_exactly_one_attempt(self):
        fake=FakeExchange()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda _: self.attempt(fake),range(3)))
        self.assertEqual(sum(r.state=="observed_unverified" for r in results),1)
        self.assertEqual(len(fake.attempts),1)

    def test_stale_fence_and_wrong_scope_do_not_dispatch(self):
        fake=FakeExchange()
        self.assertEqual(self.attempt(fake,fence=self.fence+1).state,"hold")
        self.assertEqual(self.attempt(fake,account="0x"+"2"*40).state,"hold")
        self.assertEqual(fake.attempts,[])
        self.assertEqual(self.journal.inspect(**SCOPE)[4],"reserved")

    def test_invalid_fake_type_never_marks_attempt(self):
        self.assertEqual(self.attempt(object()).state,"hold")
        self.assertEqual(self.journal.inspect(**SCOPE)[4],"reserved")

if __name__=="__main__":
    unittest.main()
