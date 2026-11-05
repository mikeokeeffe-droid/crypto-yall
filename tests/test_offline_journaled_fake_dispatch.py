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
        fake=FakeExchange()
        original=fake.record_fake_attempt
        observed=[]
        def inspect_before_fake(token,cloid):
            record=journal.inspect(**SCOPE)
            observed.append((record[4],record[2]))
            return original(token,cloid)
        fake.record_fake_attempt=inspect_before_fake
        self.assertEqual(self.attempt(fake).state,"observed_unverified")
        self.assertEqual(observed,[("dispatch_unknown",self.cloid)])
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

    def test_restart_after_fake_observation_retains_uncertain_marker(self):
        fake=FakeExchange()
        self.assertEqual(self.attempt(fake).state,"observed_unverified")
        self.journal=OfflineRestartJournal(self.path)
        self.assertEqual(self.journal.inspect(**SCOPE)[4],"dispatch_unknown")
        self.assertIsNone(self.journal.reserve(bot="aggressive",**SCOPE))
        self.assertEqual(self.attempt(fake).state,"hold")
        self.assertEqual(len(fake.attempts),1)

    def test_fake_callback_failure_does_not_roll_back_durable_marker(self):
        fake=FakeExchange()
        def crash(token,cloid):
            raise RuntimeError("synthetic process interruption")
        fake.record_fake_attempt=crash
        self.assertEqual(self.attempt(fake).state,"hold")
        self.journal=OfflineRestartJournal(self.path)
        self.assertEqual(self.journal.inspect(**SCOPE)[4],"dispatch_unknown")
        self.assertFalse(self.journal.mark_dispatch_unknown(
            token=self.token,fence=self.fence,**SCOPE))

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

    def test_separate_restarted_journal_instances_dispatch_at_most_once(self):
        fake=FakeExchange()
        def competing_instance(_):
            journal=OfflineRestartJournal(self.path)
            return simulate_journaled_once(
                journal=journal, fake=fake, token=self.token,
                fence=self.fence, **SCOPE)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(competing_instance,range(12)))
        self.assertEqual(sum(r.state=="observed_unverified" for r in results),1)
        self.assertEqual(len(fake.attempts),1)
        self.assertEqual(OfflineRestartJournal(self.path).inspect(**SCOPE)[4],
                         "dispatch_unknown")

    def test_concurrent_restarts_after_lost_reply_do_not_retry(self):
        fake=FakeExchange()
        def lose_reply(token,cloid):
            fake.attempts.append((token,cloid))
            raise TimeoutError("synthetic accepted but reply lost")
        fake.record_fake_attempt=lose_reply
        self.assertEqual(self.attempt(fake).state,"hold")
        def recovered_instance(_):
            journal=OfflineRestartJournal(self.path)
            return simulate_journaled_once(
                journal=journal, fake=fake, token=self.token,
                fence=self.fence, **SCOPE)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(recovered_instance,range(12)))
        self.assertTrue(all(r.state=="hold" for r in results))
        self.assertEqual(len(fake.attempts),1)
        self.assertIsNone(OfflineRestartJournal(self.path).reserve(
            bot="intraday",**SCOPE))

    def test_concurrent_restarts_after_pre_send_crash_do_not_send(self):
        self.assertTrue(self.journal.mark_dispatch_unknown(
            token=self.token,fence=self.fence,**SCOPE))
        fake=FakeExchange()
        def recovered_instance(_):
            journal=OfflineRestartJournal(self.path)
            return simulate_journaled_once(
                journal=journal, fake=fake, token=self.token,
                fence=self.fence, **SCOPE)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(recovered_instance,range(12)))
        self.assertTrue(all(r.state=="hold" for r in results))
        self.assertEqual(fake.attempts,[])
        self.assertEqual(OfflineRestartJournal(self.path).inspect(**SCOPE)[4],
                         "dispatch_unknown")

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
