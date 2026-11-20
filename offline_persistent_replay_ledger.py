"""Disposable SQLite-backed nonce ledger for offline authentication fixtures.

Persistent per-principal nonce uniqueness is enforced by SQLite transactions.
No production database, network, signing keys, or exchange SDK.
"""
import sqlite3

class OfflinePersistentReplayLedger:
    def __init__(self,path,*,create=False):
        self.path=path
        if create:
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE IF NOT EXISTS replay_nonces ("
                           "principal TEXT NOT NULL, nonce TEXT NOT NULL, "
                           "PRIMARY KEY(principal,nonce))")
        else:
            # Read-write mode must fail if the file is absent.
            with sqlite3.connect("file:"+path+"?mode=rw",uri=True) as db:
                row=db.execute("SELECT name FROM sqlite_master "
                               "WHERE type='table' AND name='replay_nonces'").fetchone()
                if row is None:
                    raise RuntimeError("replay ledger schema missing")

    def consume(self,principal,nonce):
        if type(principal) is not str or not principal or type(nonce) is not str or not nonce:
            return False
        try:
            with sqlite3.connect("file:"+self.path+"?mode=rw",uri=True,
                                 timeout=5) as db:
                db.execute("INSERT INTO replay_nonces(principal,nonce) VALUES (?,?)",
                           (principal,nonce))
            return True
        except sqlite3.IntegrityError:
            return False
        # Database unavailable/corrupt/locked must fail closed at caller.
