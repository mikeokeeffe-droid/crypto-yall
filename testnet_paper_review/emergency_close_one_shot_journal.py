"""Independent, persistent *single-host* one-use emergency-close claim journal.

This differs from the already-consumed ENTRY journal. One emergency close
attempt can be persisted BEFORE network transmission, never retried after a
timeout/unknown ACK, and never recreated automatically. It does NOT allow
orders by itself and is not distributed fencing across hosts.
"""
import os
from pathlib import Path
import re
import sqlite3
import stat

JOURNAL_PATH="/home/testadmin/crypto-yall-testnet-state/testnet-emergency-close.sqlite3"
HASH=re.compile(r"[0-9a-f]{64}\Z")
REQUEST=re.compile(r"[a-z0-9][a-z0-9-]{7,63}\Z")


class EmergencyJournalHold(RuntimeError):
    pass


class EmergencyCloseJournal:
    def __init__(self,path=JOURNAL_PATH,*,initialize=False,read_only=False):
        if (path != JOURNAL_PATH or type(initialize) is not bool
                or type(read_only) is not bool or (initialize and read_only)):
            raise EmergencyJournalHold("HOLD: unapproved emergency journal path")
        p=Path(path)
        root=p.parent
        if (root.is_symlink() or not root.is_dir()
                or root.stat().st_uid!=os.getuid()
                or stat.S_IMODE(root.stat().st_mode)!=0o700
                or p.is_symlink()):
            raise EmergencyJournalHold("HOLD: emergency journal directory unsafe")
        if initialize:
            try:
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|
                           getattr(os,"O_NOFOLLOW",0),0o600)
                os.close(fd)
            except OSError as exc:
                raise EmergencyJournalHold("HOLD: cannot exclusively create rescue journal") from exc
        elif not p.is_file():
            raise EmergencyJournalHold("HOLD: emergency journal missing; never recreate")
        if (not p.is_file() or p.is_symlink() or p.stat().st_uid!=os.getuid()
                or stat.S_IMODE(p.stat().st_mode)!=0o600):
            raise EmergencyJournalHold("HOLD: emergency journal permissions unsafe")
        try:
            self.db=sqlite3.connect(p.as_uri()+("?mode=ro" if read_only else "?mode=rw"),
                                   uri=True,isolation_level=None,timeout=3)
            self.db.execute("PRAGMA busy_timeout=3000")
            if read_only:
                self.db.execute("PRAGMA query_only=ON")
            else:
                self.db.execute("PRAGMA synchronous=FULL")
                self.db.execute("PRAGMA journal_mode=DELETE")
            if initialize:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute(
                    "CREATE TABLE control (id INTEGER PRIMARY KEY CHECK(id=1), "
                    "version INTEGER NOT NULL CHECK(version=1))"
                )
                self.db.execute("INSERT INTO control VALUES(1,1)")
                self.db.execute(
                    "CREATE TABLE close_claim (id INTEGER PRIMARY KEY CHECK(id=1),"
                    "request_id TEXT NOT NULL, plan_hash TEXT NOT NULL,"
                    "status TEXT NOT NULL CHECK(status IN ('RESERVED','ACK_SEEN','UNKNOWN_ACK')))"
                )
                self.db.execute("COMMIT")
            if self.db.execute("PRAGMA quick_check").fetchone()!=("ok",):
                raise EmergencyJournalHold("HOLD: corrupted emergency journal")
            if self.db.execute("SELECT id,version FROM control").fetchall()!=[(1,1)]:
                raise EmergencyJournalHold("HOLD: unrecognised emergency journal schema")
            if self.db.execute("SELECT COUNT(*) FROM close_claim").fetchone()[0]>1:
                raise EmergencyJournalHold("HOLD: multiple emergency claims")
        except (sqlite3.DatabaseError,EmergencyJournalHold) as exc:
            if hasattr(self,"db"):
                if self.db.in_transaction:self.db.execute("ROLLBACK")
                self.db.close()
            raise EmergencyJournalHold("HOLD: emergency journal invalid; do not reset") from exc

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self,*_):
        self.close()

    def view(self):
        try:
            rows=self.db.execute(
                "SELECT request_id,plan_hash,status FROM close_claim WHERE id=1"
            ).fetchall()
            if len(rows)>1:raise EmergencyJournalHold("HOLD: ambiguous rescue claim")
            return rows[0] if rows else None
        except sqlite3.DatabaseError as exc:
            raise EmergencyJournalHold("HOLD: rescue state unreadable") from exc

    def reserve(self,*,request_id,plan_hash):
        if (type(request_id) is not str or not REQUEST.fullmatch(request_id)
                or type(plan_hash) is not str or not HASH.fullmatch(plan_hash)):
            raise EmergencyJournalHold("HOLD: bad emergency request identity")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            if self.view() is not None:
                raise EmergencyJournalHold("HOLD: emergency submission already spent")
            self.db.execute(
                "INSERT INTO close_claim VALUES(1,?,?,'RESERVED')",
                (request_id,plan_hash)
            )
            self.db.execute("COMMIT")
        except (sqlite3.DatabaseError,EmergencyJournalHold) as exc:
            if self.db.in_transaction:self.db.execute("ROLLBACK")
            raise EmergencyJournalHold("HOLD: duplicate/competing rescue claim") from exc
        return "EMERGENCY_CLAIM_SPENT_NO_RETRY"

    def note_ack(self,*,request_id,known_ack):
        if type(known_ack) is not bool or type(request_id) is not str:
            raise EmergencyJournalHold("HOLD: invalid emergency ACK")
        new_state="ACK_SEEN" if known_ack else "UNKNOWN_ACK"
        try:
            self.db.execute("BEGIN IMMEDIATE")
            cur=self.db.execute(
                "UPDATE close_claim SET status=? WHERE id=1 AND request_id=? AND status='RESERVED'",
                (new_state,request_id)
            )
            if cur.rowcount!=1:
                raise EmergencyJournalHold("HOLD: stale or missing emergency claim")
            self.db.execute("COMMIT")
        except (sqlite3.DatabaseError,EmergencyJournalHold) as exc:
            if self.db.in_transaction:self.db.execute("ROLLBACK")
            raise EmergencyJournalHold("HOLD: emergency ACK storage failed") from exc
        return "HOLD_UNTIL_EXCHANGE_CONFIRMS_FLAT"
