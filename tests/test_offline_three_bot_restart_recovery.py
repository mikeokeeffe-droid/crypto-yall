"""Offline three-bot restart recovery and missing-state fail-closed tests.

Uses only disposable SQLite files. Never dispatches or closes a trade.
"""
import os
import tempfile
import unittest
from offline_sender_restart_journal import OfflineRestartJournal
from offline_persistent_replay_ledger import OfflinePersistentReplayLedger

ACCOUNT="0x"+"1"*40
BOTS=("daily","intraday","aggressive")

class OfflineThreeBotRestartRecoveryTests(unittest.TestCase):
    def test_reserved_scope_survives_reopen_and_blocks_other_bots(self):
        with tempfile.TemporaryDirectory() as directory:
            path=os.path.join(directory,"journal.sqlite")
            first=OfflineRestartJournal(path,create=True)
            claim=first.reserve(bot="daily",environment="mainnet",account=ACCOUNT,
                                dex="",coin="SOL")
            self.assertIsNotNone(claim)
            del first
            for bot in BOTS:
                reopened=OfflineRestartJournal(path)
                self.assertIsNone(reopened.reserve(
                    bot=bot,environment="mainnet",account=ACCOUNT,dex="",coin="SOL"))
                stored=reopened.inspect(environment="mainnet",account=ACCOUNT,
                                        dex="",coin="SOL")
                self.assertEqual(stored[0],"daily")
                self.assertEqual(stored[1],claim[0])
                self.assertEqual(stored[3],claim[2])

    def test_unknown_dispatch_state_survives_restart_and_blocks_all_bots(self):
        with tempfile.TemporaryDirectory() as directory:
            path=os.path.join(directory,"journal.sqlite")
            first=OfflineRestartJournal(path,create=True)
            claim=first.reserve(bot="intraday",environment="mainnet",
                                account=ACCOUNT,dex="",coin="SOL")
            self.assertTrue(first.mark_dispatch_unknown(
                environment="mainnet",account=ACCOUNT,dex="",coin="SOL",
                token=claim[0],fence=claim[2]))
            for bot in BOTS:
                reopened=OfflineRestartJournal(path)
                self.assertIsNone(reopened.reserve(
                    bot=bot,environment="mainnet",account=ACCOUNT,dex="",coin="SOL"))
                self.assertEqual(reopened.inspect(
                    environment="mainnet",account=ACCOUNT,dex="",coin="SOL")[4],
                    "dispatch_unknown")

    def test_missing_journal_cannot_recreate_or_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            path=os.path.join(directory,"journal.sqlite")
            OfflineRestartJournal(path,create=True)
            os.unlink(path)
            with self.assertRaises(FileNotFoundError):
                OfflineRestartJournal(path)
            self.assertFalse(os.path.exists(path))

    def test_nonce_persists_across_replay_ledger_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path=os.path.join(directory,"nonces.sqlite")
            first=OfflinePersistentReplayLedger(path,create=True)
            self.assertTrue(first.consume("uid:daily","restart-nonce"))
            reopened=OfflinePersistentReplayLedger(path)
            self.assertFalse(reopened.consume("uid:daily","restart-nonce"))

if __name__=="__main__":
    unittest.main()
