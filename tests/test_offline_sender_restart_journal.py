"""Offline SQLite journal tests: file persistence, no actual dispatch."""
import concurrent.futures
import os
import tempfile
import unittest
from offline_sender_restart_journal import OfflineRestartJournal

SCOPE = dict(environment="mainnet",account="0x"+"1"*40,dex="",coin="SOL")

class RestartJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name,"sender-fixture.sqlite")
    def tearDown(self):
        self.temp.cleanup()

    def test_restart_retains_unresolved_claim_and_cloid(self):
        journal = OfflineRestartJournal(self.path)
        token,cloid,fence = journal.reserve(bot="daily",**SCOPE)
        self.assertTrue(journal.mark_dispatch_unknown(token=token,fence=fence,**SCOPE))
        restarted = OfflineRestartJournal(self.path)
        self.assertEqual(restarted.inspect(**SCOPE),("daily",token,cloid,fence,"dispatch_unknown"))
        self.assertIsNone(restarted.reserve(bot="intraday",**SCOPE))
        self.assertFalse(restarted.mark_dispatch_unknown(token=token,fence=fence,**SCOPE))

    def test_restart_before_dispatch_still_blocks_reassignment(self):
        journal = OfflineRestartJournal(self.path)
        token,cloid,fence = journal.reserve(bot="aggressive",**SCOPE)
        restarted = OfflineRestartJournal(self.path)
        self.assertEqual(restarted.inspect(**SCOPE)[-1],"reserved")
        self.assertIsNone(restarted.reserve(bot="daily",**SCOPE))
        self.assertTrue(restarted.mark_dispatch_unknown(token=token,fence=fence,**SCOPE))

    def test_stale_token_or_fence_cannot_mark_dispatch(self):
        journal = OfflineRestartJournal(self.path)
        token,_,fence = journal.reserve(bot="daily",**SCOPE)
        self.assertFalse(journal.mark_dispatch_unknown(token="other",fence=fence,**SCOPE))
        self.assertFalse(journal.mark_dispatch_unknown(token=token,fence=fence+1,**SCOPE))
        self.assertFalse(journal.mark_dispatch_unknown(token=token,fence=True,**SCOPE))
        self.assertEqual(journal.inspect(**SCOPE)[-1],"reserved")

    def test_competing_journal_instances_one_claim(self):
        def attempt(bot):
            return OfflineRestartJournal(self.path).reserve(bot=bot,**SCOPE)
        OfflineRestartJournal(self.path)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(attempt,("daily","intraday","aggressive")))
        self.assertEqual(sum(r is not None for r in results),1)

    def test_no_exchange_sender_methods(self):
        import offline_sender_restart_journal as module
        self.assertFalse(hasattr(module,"market_open"))
        self.assertFalse(hasattr(module,"submit_order"))

if __name__=="__main__":
    unittest.main()
