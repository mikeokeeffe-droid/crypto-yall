"""Offline separate-process coordinator smoke and fail-closed tests."""
import os
import tempfile
import unittest
from offline_sender_restart_journal import OfflineRestartJournal
from offline_process_coordinator_fixture import OfflineProcessCoordinator

ACCOUNT="0x"+"1"*40
SCOPE=dict(requested_bot="daily",environment="mainnet",
           account=ACCOUNT,dex="",coin="SOL")
PRINCIPALS={"daily-principal":("daily","mainnet",ACCOUNT),
            "intraday-principal":("intraday","mainnet",ACCOUNT)}

class OfflineProcessCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=os.path.join(self.temp.name,"claims.sqlite")
        OfflineRestartJournal(self.path,create=True)
    def tearDown(self):
        self.temp.cleanup()

    def test_separate_process_accepts_one_verified_claim_only(self):
        coordinator=OfflineProcessCoordinator(self.path,PRINCIPALS)
        try:
            self.assertEqual(coordinator.request(
                "daily-principal","request_entry",SCOPE),("reserved",False))
            self.assertEqual(coordinator.request(
                "daily-principal","request_entry",SCOPE),("hold",False))
            self.assertEqual(coordinator.request(
                "intraday-principal","request_entry",
                dict(SCOPE,requested_bot="intraday")),("hold",False))
        finally:
            coordinator.close()
        self.assertEqual(OfflineRestartJournal(self.path).inspect(
            environment="mainnet",account=ACCOUNT,dex="",coin="SOL")[0],"daily")

    def test_unsupported_operations_and_spoofing_hold(self):
        coordinator=OfflineProcessCoordinator(self.path,PRINCIPALS)
        try:
            self.assertEqual(coordinator.request(
                "daily-principal","request_dispatch",SCOPE),("hold",False))
            self.assertEqual(coordinator.request(
                "daily-principal","request_close",SCOPE),("hold",False))
            self.assertEqual(coordinator.request(
                "daily-principal","request_entry",
                dict(SCOPE,requested_bot="intraday")),("hold",False))
            self.assertEqual(coordinator.request(
                "unknown","request_entry",SCOPE),("hold",False))
        finally:
            coordinator.close()

    def test_process_restart_preserves_claim(self):
        first=OfflineProcessCoordinator(self.path,PRINCIPALS)
        try:
            self.assertEqual(first.request(
                "daily-principal","request_entry",SCOPE),("reserved",False))
        finally:
            first.close()
        second=OfflineProcessCoordinator(self.path,PRINCIPALS)
        try:
            self.assertEqual(second.request(
                "daily-principal","request_entry",SCOPE),("hold",False))
        finally:
            second.close()

    def test_missing_journal_prevents_process_start(self):
        os.unlink(self.path)
        with self.assertRaises(RuntimeError):
            OfflineProcessCoordinator(self.path,PRINCIPALS)

if __name__=="__main__":
    unittest.main()
