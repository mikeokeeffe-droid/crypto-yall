"""Offline-only atomic coordinator transaction regression tests."""
import os
import tempfile
import unittest
from offline_atomic_coordinator_fixture import OfflineAtomicCoordinator

ACCOUNT="0x"+"1"*40

class AtomicCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=os.path.join(self.temp.name,"atomic.sqlite")
        self.coordinator=OfflineAtomicCoordinator(self.path,create=True)
        self.args=dict(principal="uid1001:daily",nonce="first",bot="daily",
                       environment="mainnet",account=ACCOUNT,dex="",coin="SOL")

    def test_atomic_commit_and_duplicate_nonce_hold(self):
        self.assertEqual(self.coordinator.reserve(**self.args),("reserved_offline_only",False))
        self.assertEqual(self.coordinator.reserve(**self.args),("hold",False))
        self.assertIsNotNone(self.coordinator.inspect(
            environment="mainnet",account=ACCOUNT,dex="",coin="SOL"))

    def test_crash_after_nonce_rolls_back_nonce_and_claim(self):
        self.assertEqual(self.coordinator.reserve(**self.args,inject_failure="after_nonce"),("hold",False))
        self.assertIsNone(self.coordinator.inspect(
            environment="mainnet",account=ACCOUNT,dex="",coin="SOL"))
        self.assertEqual(self.coordinator.reserve(**self.args),("reserved_offline_only",False))

    def test_crash_after_claim_rolls_back_both(self):
        self.assertEqual(self.coordinator.reserve(**self.args,inject_failure="after_claim"),("hold",False))
        self.assertIsNone(self.coordinator.inspect(
            environment="mainnet",account=ACCOUNT,dex="",coin="SOL"))
        self.assertEqual(self.coordinator.reserve(**self.args),("reserved_offline_only",False))

    def test_scope_collision_rolls_back_second_nonce(self):
        self.assertEqual(self.coordinator.reserve(**self.args),("reserved_offline_only",False))
        second=dict(self.args,nonce="second",principal="uid1002:intraday",bot="intraday")
        self.assertEqual(self.coordinator.reserve(**second),("hold",False))
        with self.coordinator._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM replay_nonces").fetchone()[0],1)

    def test_restart_preserves_claim_and_nonce(self):
        self.assertEqual(self.coordinator.reserve(**self.args),("reserved_offline_only",False))
        restarted=OfflineAtomicCoordinator(self.path)
        self.assertEqual(restarted.reserve(**self.args),("hold",False))
        self.assertIsNotNone(restarted.inspect(
            environment="mainnet",account=ACCOUNT,dex="",coin="SOL"))

    def test_missing_file_not_recreated(self):
        os.unlink(self.path)
        with self.assertRaises(FileNotFoundError):
            OfflineAtomicCoordinator(self.path)
        self.assertFalse(os.path.exists(self.path))

if __name__=="__main__":
    unittest.main()
