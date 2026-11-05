"""Disposable SQLite restart journal for the offline sender prototype only.

No SDK, network, signer, trading credentials or live order capability.
SQLite file is created only by the test harness; no production path.
"""
import sqlite3
import os
from uuid import uuid4

_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
 environment TEXT NOT NULL, account TEXT NOT NULL, dex TEXT NOT NULL,
 coin TEXT NOT NULL, bot TEXT NOT NULL, token TEXT NOT NULL UNIQUE,
 cloid TEXT NOT NULL UNIQUE, fence INTEGER NOT NULL UNIQUE,
 state TEXT NOT NULL CHECK(state IN ('reserved','dispatch_unknown')),
 PRIMARY KEY(environment,account,dex,coin)
);
"""

class OfflineRestartJournal:
    def __init__(self, path, *, create=False):
        # Reopening a missing file must never silently create a fresh,
        # empty claim table that permits a second fake submission.
        self.path = path
        if create:
            if os.path.exists(path):
                raise FileExistsError("fixture journal already exists")
            with sqlite3.connect(path) as db:
                db.executescript(_SCHEMA)
        elif not os.path.isfile(path):
            raise FileNotFoundError("missing journal; fail closed")
        with self._connect() as db:
            check = db.execute("PRAGMA integrity_check").fetchone()
            if check != ("ok",):
                raise sqlite3.DatabaseError("damaged journal; fail closed")
            required = {"environment", "account", "dex", "coin", "bot",
                        "token", "cloid", "fence", "state"}
            columns = {row[1] for row in db.execute("PRAGMA table_info(claims)")}
            if not required.issubset(columns):
                raise sqlite3.DatabaseError("incomplete journal schema; fail closed")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def reserve(self, *, bot, environment, account, dex, coin):
        from offline_shared_sender_prototype import OfflineSharedSender
        scope = OfflineSharedSender._scope(environment, account, dex, coin)
        if scope is None or bot not in ("daily","intraday","aggressive"):
            return None
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            fence = db.execute("SELECT COALESCE(MAX(fence),0)+1 FROM claims").fetchone()[0]
            token, cloid = str(uuid4()), "0x" + uuid4().hex
            try:
                db.execute(
                    "INSERT INTO claims VALUES(?,?,?,?,?,?,?,?,?)",
                    (*scope,bot,token,cloid,fence,"reserved"),
                )
            except sqlite3.IntegrityError:
                db.rollback()
                return None
            db.commit()
            return (token,cloid,fence)

    def mark_dispatch_unknown(self, *, environment, account, dex, coin, token, fence):
        """Persist ambiguous send marker before any simulated external action."""
        from offline_shared_sender_prototype import OfflineSharedSender
        scope = OfflineSharedSender._scope(environment, account, dex, coin)
        if scope is None or type(token) is not str or type(fence) is not int:
            return False
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                """UPDATE claims SET state='dispatch_unknown'
                   WHERE environment=? AND account=? AND dex=? AND coin=?
                     AND token=? AND fence=? AND state='reserved'""",
                (*scope,token,fence),
            ).rowcount
            db.commit()
            return changed == 1

    def inspect(self, *, environment, account, dex, coin):
        from offline_shared_sender_prototype import OfflineSharedSender
        scope = OfflineSharedSender._scope(environment, account, dex, coin)
        if scope is None:
            return None
        with self._connect() as db:
            return db.execute(
                """SELECT bot,token,cloid,fence,state FROM claims
                   WHERE environment=? AND account=? AND dex=? AND coin=?""",
                scope,
            ).fetchone()
