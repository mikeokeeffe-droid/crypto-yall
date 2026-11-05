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
        journal = OfflineRestartJournal(self.path, create=True)
        token,cloid,fence = journal.reserve(bot="daily",**SCOPE)
        self.assertTrue(journal.mark_dispatch_unknown(token=token,fence=fence,**SCOPE))
        restarted = OfflineRestartJournal(self.path)
        self.assertEqual(restarted.inspect(**SCOPE),("daily",token,cloid,fence,"dispatch_unknown"))
        self.assertIsNone(restarted.reserve(bot="intraday",**SCOPE))
        self.assertFalse(restarted.mark_dispatch_unknown(token=token,fence=fence,**SCOPE))

    def test_restart_before_dispatch_still_blocks_reassignment(self):
        journal = OfflineRestartJournal(self.path, create=True)
        token,cloid,fence = journal.reserve(bot="aggressive",**SCOPE)
        restarted = OfflineRestartJournal(self.path)
        self.assertEqual(restarted.inspect(**SCOPE)[-1],"reserved")
        self.assertIsNone(restarted.reserve(bot="daily",**SCOPE))
        self.assertTrue(restarted.mark_dispatch_unknown(token=token,fence=fence,**SCOPE))

    def test_stale_token_or_fence_cannot_mark_dispatch(self):
        journal = OfflineRestartJournal(self.path, create=True)
        token,_,fence = journal.reserve(bot="daily",**SCOPE)
        self.assertFalse(journal.mark_dispatch_unknown(token="other",fence=fence,**SCOPE))
        self.assertFalse(journal.mark_dispatch_unknown(token=token,fence=fence+1,**SCOPE))
        self.assertFalse(journal.mark_dispatch_unknown(token=token,fence=True,**SCOPE))
        self.assertEqual(journal.inspect(**SCOPE)[-1],"reserved")

    def test_competing_journal_instances_one_claim(self):
        def attempt(bot):
            return OfflineRestartJournal(self.path).reserve(bot=bot,**SCOPE)
        OfflineRestartJournal(self.path, create=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(attempt,("daily","intraday","aggressive")))
        self.assertEqual(sum(r is not None for r in results),1)

    def test_missing_journal_fails_closed_instead_of_creating_empty_claims(self):
        with self.assertRaises(FileNotFoundError):
            OfflineRestartJournal(self.path)
        self.assertFalse(os.path.exists(self.path))

    def test_corrupted_journal_fails_closed(self):
        with open(self.path,"wb") as file:
            file.write(b"not a sqlite journal")
        with self.assertRaises(Exception):
            OfflineRestartJournal(self.path)

    def test_existing_journal_cannot_be_recreated_as_fresh(self):
        journal=OfflineRestartJournal(self.path,create=True)
        token,cloid,fence=journal.reserve(bot="daily",**SCOPE)
        with self.assertRaises(FileExistsError):
            OfflineRestartJournal(self.path,create=True)
        self.assertEqual(OfflineRestartJournal(self.path).inspect(**SCOPE),
                         ("daily",token,cloid,fence,"reserved"))

    def test_empty_sqlite_file_without_claims_schema_fails_closed(self):
        import sqlite3
        sqlite3.connect(self.path).close()
        with self.assertRaises(sqlite3.DatabaseError):
            OfflineRestartJournal(self.path)

    def test_rolled_back_dispatch_marker_remains_reserved_and_claimed(self):
        import sqlite3
        journal=OfflineRestartJournal(self.path,create=True)
        token,cloid,fence=journal.reserve(bot="daily",**SCOPE)
        # Simulate process interruption before the SQLite transaction commits.
        with journal._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE claims SET state='dispatch_unknown' WHERE token=?",
                (token,),
            )
            db.rollback()
        restarted=OfflineRestartJournal(self.path)
        self.assertEqual(restarted.inspect(**SCOPE),
                         ("daily",token,cloid,fence,"reserved"))
        self.assertIsNone(restarted.reserve(bot="intraday",**SCOPE))
        # Reserved is not proof that no send happened: never auto-release it.
        self.assertTrue(restarted.mark_dispatch_unknown(
            token=token,fence=fence,**SCOPE))
        self.assertIsNone(OfflineRestartJournal(self.path).reserve(
            bot="aggressive",**SCOPE))

    def test_uncommitted_new_claim_disappears_without_releasing_prior_claim(self):
        journal=OfflineRestartJournal(self.path,create=True)
        token,cloid,fence=journal.reserve(bot="daily",**SCOPE)
        with journal._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM claims WHERE token=?",(token,))
            db.rollback()
        restarted=OfflineRestartJournal(self.path)
        self.assertEqual(restarted.inspect(**SCOPE),
                         ("daily",token,cloid,fence,"reserved"))
        self.assertIsNone(restarted.reserve(bot="intraday",**SCOPE))

    def test_daily_cannot_take_intraday_reserved_claim_after_restart(self):
        journal=OfflineRestartJournal(self.path,create=True)
        token,cloid,fence=journal.reserve(bot="intraday",**SCOPE)
        restarted=OfflineRestartJournal(self.path)
        self.assertIsNone(restarted.reserve(bot="daily",**SCOPE))
        self.assertEqual(restarted.inspect(**SCOPE),
                         ("intraday",token,cloid,fence,"reserved"))

    def test_aggressive_cannot_take_daily_unknown_dispatch_after_restart(self):
        journal=OfflineRestartJournal(self.path,create=True)
        token,cloid,fence=journal.reserve(bot="daily",**SCOPE)
        self.assertTrue(journal.mark_dispatch_unknown(
            token=token,fence=fence,**SCOPE))
        restarted=OfflineRestartJournal(self.path)
        self.assertIsNone(restarted.reserve(bot="aggressive",**SCOPE))
        self.assertEqual(restarted.inspect(**SCOPE),
                         ("daily",token,cloid,fence,"dispatch_unknown"))

    def test_no_exchange_sender_methods(self):
        import offline_sender_restart_journal as module
        self.assertFalse(hasattr(module,"market_open"))
        self.assertFalse(hasattr(module,"submit_order"))

if __name__=="__main__":
    unittest.main()
