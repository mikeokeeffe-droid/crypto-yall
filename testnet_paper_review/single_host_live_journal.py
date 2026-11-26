"""Persistent *single-host* one-shot sender journal (no trading API).

Unlike the disposable review fixture, this records a real immutable request
fingerprint on a dedicated host before ANY order-sender network action.
It is never automatically recreated after a crash/lost file and never
releases a consumed request. It is not distributed fencing, and cannot protect
another trading process using the same Hyperliquid account.

The host operator must explicitly create a new empty journal in a dedicated,
private persistent directory, once. The sender MUST NOT run from GitHub Actions
or a transient runner with this SQLite journal.
"""
import os
from pathlib import Path
import sqlite3
import stat
import re

SCHEMA_VERSION = 1
ACCOUNT = "0xf14348bdf59ba186f9cdd0fc5f369e1f6d3b7dc0"
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{7,63}\Z")
HASH_PATTERN = re.compile(r"[a-f0-9]{64}\Z")


class PersistentHold(RuntimeError):
    pass


def _safe_existing_parent(path):
    p = Path(path)
    if not p.is_absolute() or p.name != "testnet-one-shot.sqlite3":
        raise PersistentHold("HOLD: invalid dedicated journal filename")
    if p.parent.is_symlink() or not p.parent.is_dir():
        raise PersistentHold("HOLD: missing or redirected persistent directory")
    pstat = p.parent.stat()
    if pstat.st_uid != os.getuid() or stat.S_IMODE(pstat.st_mode) != 0o700:
        raise PersistentHold("HOLD: persistent directory must be owned and mode 0700")
    if p.is_symlink():
        raise PersistentHold("HOLD: journal symlink forbidden")
    return p


class SingleHostOneShotJournal:
    def __init__(self, path, *, initialize=False, read_only=False):
        self.path = _safe_existing_parent(path)
        if (type(initialize) is not bool or type(read_only) is not bool
                or (initialize and read_only)):
            raise PersistentHold("HOLD: explicit initialization required")
        if initialize:
            if self.path.exists():
                raise PersistentHold("HOLD: journal already exists: no reset")
            fd = None
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                             getattr(os, "O_NOFOLLOW", 0), 0o600)
            except OSError as e:
                raise PersistentHold("HOLD: cannot exclusively initialize journal") from e
            finally:
                if fd is not None:
                    os.close(fd)
        elif not self.path.is_file():
            raise PersistentHold("HOLD: missing existing journal (never recreate)")
        if (not self.path.is_file() or self.path.is_symlink()
                or self.path.stat().st_uid != os.getuid()
                or stat.S_IMODE(self.path.stat().st_mode) != 0o600):
            raise PersistentHold("HOLD: journal owner/mode not private")
        try:
            self.db = sqlite3.connect(
                self.path.as_uri() + ("?mode=ro" if read_only else "?mode=rw"), uri=True,
                isolation_level=None, timeout=3
            )
            self.db.execute("PRAGMA busy_timeout=3000")
            if read_only:
                self.db.execute("PRAGMA query_only=ON")
            else:
                self.db.execute("PRAGMA journal_mode=DELETE")
                self.db.execute("PRAGMA synchronous=FULL")
            if initialize:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute("CREATE TABLE control (id INTEGER PRIMARY KEY CHECK(id=1),"
                                " frozen INTEGER NOT NULL CHECK(frozen IN (0,1)),"
                                " version INTEGER NOT NULL)")
                self.db.execute("INSERT INTO control VALUES(1,0,?)",(SCHEMA_VERSION,))
                self.db.execute(
                    "CREATE TABLE one_shot (account TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,"
                    " request_hash TEXT NOT NULL, code_sha TEXT NOT NULL,"
                    " stage TEXT NOT NULL CHECK(stage IN "
                    "('RESERVED','UNKNOWN_ACK','RESPONSE_SEEN','RECONCILED','FROZEN')))"
                )
                self.db.execute("COMMIT")
            if self.db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise PersistentHold("HOLD: corrupt persistent journal")
            rows=self.db.execute("SELECT id,frozen,version FROM control").fetchall()
            if rows not in ([(1,0,SCHEMA_VERSION)],[(1,1,SCHEMA_VERSION)]):
                raise PersistentHold("HOLD: missing/invalid persistent control row")
            for row in self.db.execute("SELECT account,stage FROM one_shot"):
                if row[0] != ACCOUNT:
                    raise PersistentHold("HOLD: foreign account journal record")
        except (sqlite3.DatabaseError, PersistentHold) as e:
            if hasattr(self, "db"):
                if self.db.in_transaction:self.db.execute("ROLLBACK")
                self.db.close()
            raise PersistentHold("HOLD: persistent journal invalid; do not reset") from e

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def view(self):
        try:
            frozen=self.db.execute("SELECT frozen FROM control WHERE id=1").fetchall()
            rows=self.db.execute(
                "SELECT request_id,request_hash,code_sha,stage FROM one_shot WHERE account=?",
                (ACCOUNT,)
            ).fetchall()
            if frozen not in ([(0,)],[(1,)]) or len(rows)>1:
                raise PersistentHold("HOLD: missing or ambiguous journal state")
            return {"frozen":frozen[0][0]==1,"claim":rows[0] if rows else None}
        except sqlite3.DatabaseError as e:
            raise PersistentHold("HOLD: journal read failure") from e

    def reserve(self, *, request_id, request_hash, code_sha):
        """Atomic persist-before-send. Request is NEVER reusable, even if rejected."""
        if (type(request_id) is not str or not ID_PATTERN.fullmatch(request_id)
                or type(request_hash) is not str or not HASH_PATTERN.fullmatch(request_hash)
                or type(code_sha) is not str or not re.fullmatch(r"[a-f0-9]{40}\Z",code_sha)):
            raise PersistentHold("HOLD: invalid one-shot identity")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            state=self.view()
            if state["frozen"] or state["claim"] is not None:
                raise PersistentHold("HOLD: journal already consumed/frozen")
            self.db.execute(
                "INSERT INTO one_shot(account,request_id,request_hash,code_sha,stage)"
                " VALUES(?,?,?,?,?)",
                (ACCOUNT,request_id,request_hash,code_sha,"RESERVED")
            )
            self.db.execute("COMMIT")
        except (sqlite3.DatabaseError,PersistentHold) as e:
            if self.db.in_transaction:self.db.execute("ROLLBACK")
            raise PersistentHold("HOLD: duplicate or competing one-shot") from e
        return "RESERVED_NO_RETRY"

    def report_response(self, *, request_id, known_success):
        if type(known_success) is not bool or type(request_id) is not str:
            raise PersistentHold("HOLD: invalid ACK")
        stage="RESPONSE_SEEN" if known_success else "UNKNOWN_ACK"
        try:
            self.db.execute("BEGIN IMMEDIATE")
            cur=self.db.execute(
                "UPDATE one_shot SET stage=? WHERE account=? AND request_id=?"
                " AND stage='RESERVED'",(stage,ACCOUNT,request_id))
            if cur.rowcount!=1:
                raise PersistentHold("HOLD: missing/stale one-shot ACK")
            self.db.execute("COMMIT")
        except (sqlite3.DatabaseError,PersistentHold) as e:
            if self.db.in_transaction:self.db.execute("ROLLBACK")
            raise PersistentHold("HOLD: ACK persistence failed") from e
        return "HOLD_UNTIL_INDEPENDENT_RECONCILIATION"

    def freeze(self):
        try:
            self.db.execute("BEGIN IMMEDIATE")
            cur=self.db.execute("UPDATE control SET frozen=1 WHERE id=1")
            if cur.rowcount!=1:raise PersistentHold("HOLD: freeze latch missing")
            self.db.execute("COMMIT")
        except (sqlite3.DatabaseError,PersistentHold) as e:
            if self.db.in_transaction:self.db.execute("ROLLBACK")
            raise PersistentHold("HOLD: could not persist freeze") from e
        return "FROZEN_NO_MORE_ORDERS"
