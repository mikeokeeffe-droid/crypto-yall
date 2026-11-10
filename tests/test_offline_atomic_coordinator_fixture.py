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

    def test_concurrent_same_scope_only_one_reservation(self):
        from concurrent.futures import ThreadPoolExecutor
        def attempt(i):
            return self.coordinator.reserve(**dict(
                self.args,principal="uid"+str(i)+":daily",nonce="nonce-"+str(i)))
        with ThreadPoolExecutor(max_workers=12) as pool:
            decisions=list(pool.map(attempt,range(24)))
        self.assertEqual(decisions.count(("reserved_offline_only",False)),1)
        self.assertEqual(decisions.count(("hold",False)),23)
        with self.coordinator._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claims").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM replay_nonces").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT next_fence FROM metadata").fetchone()[0],2)

    def test_concurrent_distinct_scopes_all_reserve_with_unique_fences(self):
        from concurrent.futures import ThreadPoolExecutor
        coins=("SOL","AVAX","LINK","SUI","XRP","ONDO")
        def attempt(i):
            return self.coordinator.reserve(**dict(
                self.args,principal="uid"+str(i)+":daily",
                nonce="distinct-"+str(i),coin=coins[i]))
        with ThreadPoolExecutor(max_workers=len(coins)) as pool:
            decisions=list(pool.map(attempt,range(len(coins))))
        self.assertEqual(decisions,[("reserved_offline_only",False)]*len(coins))
        with self.coordinator._connect() as db:
            claims=db.execute("SELECT coin,fence FROM claims").fetchall()
            self.assertEqual({coin for coin,_ in claims},set(coins))
            self.assertEqual({fence for _,fence in claims},set(range(1,len(coins)+1)))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM replay_nonces").fetchone()[0],len(coins))
            self.assertEqual(db.execute("SELECT next_fence FROM metadata").fetchone()[0],len(coins)+1)

    def test_rollback_survives_reopen_and_retry_uses_first_fence(self):
        for stage in ("after_nonce","after_claim"):
            with self.subTest(stage=stage):
                self.assertEqual(self.coordinator.reserve(
                    **self.args,inject_failure=stage),("hold",False))
                reopened=OfflineAtomicCoordinator(self.path)
                with reopened._connect() as db:
                    self.assertEqual(db.execute(
                        "SELECT COUNT(*) FROM replay_nonces").fetchone()[0],0)
                    self.assertEqual(db.execute(
                        "SELECT COUNT(*) FROM claims").fetchone()[0],0)
                    self.assertEqual(db.execute(
                        "SELECT next_fence FROM metadata").fetchone()[0],1)
        reopened=OfflineAtomicCoordinator(self.path)
        self.assertEqual(reopened.reserve(**self.args),("reserved_offline_only",False))
        claim=reopened.inspect(environment="mainnet",account=ACCOUNT,dex="",coin="SOL")
        self.assertEqual(claim[3],1)
        self.assertEqual(OfflineAtomicCoordinator(self.path).reserve(**self.args),
                         ("hold",False))

    def test_real_process_exit_before_commit_rolls_back(self):
        import subprocess
        import sys
        # A separate interpreter exits abruptly without commit or rollback.
        # SQLite must discard both writes and the uncommitted fence increment.
        script = """
import os, sqlite3, sys
from pathlib import Path
uri=Path(sys.argv[1]).absolute().as_uri()+'?mode=rw'
db=sqlite3.connect(uri,uri=True,isolation_level=None)
db.execute('BEGIN IMMEDIATE')
db.execute('INSERT INTO replay_nonces VALUES(?,?)',('uid1001:daily','first'))
db.execute('INSERT INTO claims VALUES(?,?,?,?,?,?,?,?,?)',
           ('mainnet',sys.argv[2],'','SOL','daily','token-test',
            '0x'+'a'*32,1,'reserved'))
db.execute('UPDATE metadata SET next_fence=2')
os._exit(17)
"""
        result=subprocess.run([sys.executable,"-c",script,self.path,ACCOUNT],
                              check=False,timeout=10)
        self.assertEqual(result.returncode,17)
        restarted=OfflineAtomicCoordinator(self.path)
        with restarted._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM replay_nonces").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claims").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT next_fence FROM metadata").fetchone()[0],1)
        self.assertEqual(restarted.reserve(**self.args),("reserved_offline_only",False))
        self.assertEqual(restarted.inspect(
            environment="mainnet",account=ACCOUNT,dex="",coin="SOL")[3],1)

    def test_real_process_exit_after_commit_before_ack_holds_on_restart(self):
        import subprocess
        import sys
        # Child commits a complete nonce+claim transaction, then dies without
        # returning any acknowledgement to its caller.
        script = """
import os, sqlite3, sys
from pathlib import Path
uri=Path(sys.argv[1]).absolute().as_uri()+'?mode=rw'
db=sqlite3.connect(uri,uri=True,isolation_level=None)
db.execute('BEGIN IMMEDIATE')
db.execute('INSERT INTO replay_nonces VALUES(?,?)',('uid1001:daily','first'))
db.execute('INSERT INTO claims VALUES(?,?,?,?,?,?,?,?,?)',
           ('mainnet',sys.argv[2],'','SOL','daily','token-test',
            '0x'+'b'*32,1,'reserved'))
db.execute('UPDATE metadata SET next_fence=2')
db.commit()
os._exit(19)
"""
        result=subprocess.run([sys.executable,"-c",script,self.path,ACCOUNT],
                              check=False,timeout=10)
        self.assertEqual(result.returncode,19)
        restarted=OfflineAtomicCoordinator(self.path)
        self.assertEqual(restarted.reserve(**self.args),("hold",False))
        self.assertEqual(restarted.reserve(
            **dict(self.args,nonce="fresh-after-lost-ack")),("hold",False))
        with restarted._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM replay_nonces").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claims").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT next_fence FROM metadata").fetchone()[0],2)
        claim=restarted.inspect(environment="mainnet",account=ACCOUNT,dex="",coin="SOL")
        self.assertEqual(claim[3],1)
        self.assertEqual(claim[4],"reserved")

    def test_rejects_replay_table_without_unique_nonce_constraint(self):
        import sqlite3
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TABLE replay_nonces")
            db.execute("CREATE TABLE replay_nonces(principal TEXT, nonce TEXT)")
        with self.assertRaises(sqlite3.DatabaseError):
            OfflineAtomicCoordinator(self.path)

    def test_rejects_claim_table_without_scope_primary_key(self):
        import sqlite3
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TABLE claims")
            db.execute("CREATE TABLE claims("
                       "environment TEXT,account TEXT,dex TEXT,coin TEXT,"
                       "bot TEXT,token TEXT,cloid TEXT,fence INTEGER,state TEXT)")
        with self.assertRaises(sqlite3.DatabaseError):
            OfflineAtomicCoordinator(self.path)

    def test_rejects_world_readable_database(self):
        os.chmod(self.path,0o644)
        with self.assertRaises(PermissionError):
            OfflineAtomicCoordinator(self.path)

    def test_rejects_symlinked_database(self):
        link=os.path.join(self.temp.name,"linked.sqlite")
        os.symlink(self.path,link)
        with self.assertRaises(PermissionError):
            OfflineAtomicCoordinator(link)

    def test_rejects_group_writable_parent_directory(self):
        os.chmod(self.temp.name,0o770)
        with self.assertRaises(PermissionError):
            OfflineAtomicCoordinator(self.path)

    def test_rejects_symlinked_parent_directory(self):
        link=os.path.join(self.temp.name,"linked-parent")
        actual=os.path.join(self.temp.name,"actual-parent")
        os.mkdir(actual,0o700)
        os.symlink(actual,link)
        target=os.path.join(actual,"atomic.sqlite")
        with open(self.path,"rb") as source, open(target,"wb") as dest:
            dest.write(source.read())
        os.chmod(target,0o600)
        with self.assertRaises(PermissionError):
            OfflineAtomicCoordinator(os.path.join(link,"atomic.sqlite"))

    def test_replaced_database_inode_holds_without_recreating_claim(self):
        import shutil
        replacement=os.path.join(self.temp.name,"replacement.sqlite")
        shutil.copy2(self.path,replacement)
        os.chmod(replacement,0o600)
        os.replace(replacement,self.path)
        self.assertEqual(self.coordinator.reserve(**self.args),("hold",False))
        with self.assertRaises(PermissionError):
            self.coordinator.inspect(environment="mainnet",account=ACCOUNT,
                                     dex="",coin="SOL")
        with OfflineAtomicCoordinator(self.path)._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claims").fetchone()[0],0)

    def test_missing_file_not_recreated(self):
        os.unlink(self.path)
        with self.assertRaises(FileNotFoundError):
            OfflineAtomicCoordinator(self.path)
        self.assertFalse(os.path.exists(self.path))

if __name__=="__main__":
    unittest.main()
