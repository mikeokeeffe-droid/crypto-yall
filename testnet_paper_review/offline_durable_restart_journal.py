"""Disposable SQLite restart/competition simulation, NEVER a trading journal.

No wallet, trading SDK, order, network, secrets, production state, or server
integration. File access is restricted to a direct child of a newly created
temporary directory whose name begins with offline-daily-review-. The durable
claim is NEVER reusable, even after a synthetic acknowledgment/reconciliation.
A real sender requires a separate design and independent security review.
"""
from pathlib import Path
import os
import sqlite3
import tempfile

from testnet_paper_review.offline_order_guard import (
    HoldError, REVIEW_WRITER, TESTNET_ACCOUNT, inspect_synthetic,
)

FILENAME = "review-only.sqlite3"
TMP_PREFIX = "offline-daily-review-"
ACCOUNT = TESTNET_ACCOUNT.lower()
ACK_STATES = {
    "unknown": "UNKNOWN_ACK_HOLD",
    "filled": "UNVERIFIED_FILL_HOLD",
    "rejected": "UNVERIFIED_REJECTION_HOLD",
}
UNCERTAIN_STATES = frozenset(ACK_STATES.values())


def _safe_path(path):
    """Reject normal repository/host DB paths and symlink redirection."""
    if not isinstance(path, (str, Path)):
        raise HoldError("HOLD: invalid disposable journal path")
    candidate = Path(path)
    root = Path(tempfile.gettempdir()).resolve()
    if (
        not candidate.is_absolute()
        or candidate.name != FILENAME
        or not candidate.parent.name.startswith(TMP_PREFIX)
        or candidate.parent == root
        or candidate.parent.parent.resolve() != root
        or not candidate.parent.is_dir()
        or candidate.parent.is_symlink()
        or candidate.is_symlink()
    ):
        raise HoldError("HOLD: journal allowed only in a direct disposable temp directory")
    return candidate


class DisposableReviewJournal:
    """Local crash/restart fixture with SQLite transactional uniqueness."""

    def __init__(self, path, *, initialize=False):
        """Open existing journal, or explicitly create a NEW disposable fixture.

        Ordinary reopen MUST NOT create missing state. Initialization requires
        an exclusively new file; a lost or corrupt record always means HOLD.
        """
        self.path = _safe_path(path)
        if type(initialize) is not bool:
            raise HoldError("HOLD: explicit fixture initialization must be boolean")
        if initialize:
            if self.path.exists() or self.path.is_symlink():
                raise HoldError("HOLD: cannot reinitialize an existing review journal")
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                flags |= getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(self.path, flags, 0o600)
                os.close(descriptor)
            except OSError as exc:
                raise HoldError("HOLD: could not exclusively initialize disposable fixture") from exc
        elif not self.path.is_file() or self.path.is_symlink():
            raise HoldError("HOLD: missing or invalid journal; never replace with a fresh one")
        try:
            # mode=rw refuses to create a missing file even if removed after
            # the initial path check. This is an offline test, not host isolation.
            self.db = sqlite3.connect(
                self.path.as_uri() + "?mode=rw", uri=True,
                isolation_level=None, timeout=5
            )
            self.db.execute("PRAGMA busy_timeout=5000")
            self.db.execute("PRAGMA synchronous=FULL")
            if initialize:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute(
                    """
                    CREATE TABLE review_only_claim (
                        account TEXT PRIMARY KEY,
                        request_id TEXT UNIQUE NOT NULL,
                        symbol TEXT NOT NULL,
                        writer TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN (
                            'STAGED_HOLD', 'UNKNOWN_ACK_HOLD',
                            'UNVERIFIED_FILL_HOLD', 'UNVERIFIED_REJECTION_HOLD',
                            'RECONCILED_HOLD', 'UNRESOLVED_HOLD'
                        ))
                    )
                    """
                )
                self.db.execute(
                    "CREATE TABLE review_only_control ("
                    "id INTEGER PRIMARY KEY CHECK(id=1),"
                    "frozen INTEGER NOT NULL CHECK(frozen IN (0,1)))"
                )
                self.db.execute(
                    "INSERT INTO review_only_control(id,frozen) VALUES(1,0)"
                )
                self.db.execute("COMMIT")

            # A previously existing empty, truncated, malformed, or tampered
            # database must not receive a new schema or a default unfrozen row.
            if self.db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise HoldError("HOLD: disposable journal integrity check failed")
            for name in ("review_only_claim", "review_only_control"):
                if self.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (name,),
                ).fetchone() != (name,):
                    raise HoldError("HOLD: missing disposable journal schema")
            controls = self.db.execute(
                "SELECT id, frozen FROM review_only_control"
            ).fetchall()
            if controls not in ([(1, 0)], [(1, 1)]):
                raise HoldError("HOLD: missing or invalid persisted freeze control")
            claims = self.db.execute(
                "SELECT account FROM review_only_claim"
            ).fetchall()
            if len(claims) > 1 or any(row != (ACCOUNT,) for row in claims):
                raise HoldError("HOLD: foreign or ambiguous journal claim")
        except (sqlite3.DatabaseError, OSError, HoldError) as exc:
            if hasattr(self, "db"):
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                self.db.close()
            raise HoldError("HOLD: journal missing, invalid or corrupted; no recovery by reset") from exc

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def view(self):
        """Read a persisted synthetic claim after a simulated restart."""
        try:
            rows = self.db.execute(
                "SELECT request_id, symbol, writer, state FROM review_only_claim WHERE account=?",
                (ACCOUNT,),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise HoldError("HOLD: unreadable fixture claim") from exc
        if len(rows) > 1:
            raise HoldError("HOLD: ambiguous fixture claims")
        return rows[0] if rows else None

    def is_frozen(self):
        """A missing or corrupt freeze record is HOLD, never permission."""
        try:
            row = self.db.execute(
                "SELECT frozen FROM review_only_control WHERE id=1"
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise HoldError("HOLD: cannot inspect disposable freeze latch") from exc
        if row not in ((0,), (1,)):
            raise HoldError("HOLD: invalid or missing disposable freeze latch")
        return row == (1,)

    def freeze_review(self):
        """One-way, durable STOP for the local synthetic fixture; no unfreeze."""
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("UPDATE review_only_control SET frozen=1 WHERE id=1")
            if self.db.execute(
                "SELECT frozen FROM review_only_control WHERE id=1"
            ).fetchone() != (1,):
                self.db.execute("ROLLBACK")
                raise HoldError("HOLD: freeze latch could not be verified")
            self.db.execute("COMMIT")
        except sqlite3.DatabaseError as exc:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise HoldError("HOLD: could not persist review-only freeze") from exc
        return "HOLD: disposable review permanently frozen; no new fixture claim"

    def stage(self, intent, snapshot, *, now_s, writer_id):
        if writer_id != REVIEW_WRITER:
            raise HoldError("HOLD: writer does not match offline review fixture")
        verdict = inspect_synthetic(intent, snapshot, now_s=now_s)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            if self.is_frozen():
                self.db.execute("ROLLBACK")
                raise HoldError("HOLD: review-only emergency freeze already latched")
            self.db.execute(
                "INSERT INTO review_only_claim(account,request_id,symbol,writer,state)"
                " VALUES (?,?,?,?,?)",
                (ACCOUNT, intent.request_id, intent.symbol, writer_id, "STAGED_HOLD"),
            )
            self.db.execute("COMMIT")
        except sqlite3.DatabaseError as exc:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise HoldError("HOLD: duplicate, competing, or locked persistent claim") from exc
        return verdict

    def simulated_ack(self, request_id, outcome):
        """Only records a synthetic response. Does NOT send or retry any order."""
        if outcome not in ACK_STATES or type(request_id) is not str:
            raise HoldError("HOLD: unsupported acknowledgment")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            cur = self.db.execute(
                "UPDATE review_only_claim SET state=?"
                " WHERE account=? AND request_id=? AND state='STAGED_HOLD'",
                (ACK_STATES[outcome], ACCOUNT, request_id),
            )
            if cur.rowcount != 1:
                self.db.execute("ROLLBACK")
                raise HoldError("HOLD: replay, wrong owner, or out-of-order acknowledgment")
            self.db.execute("COMMIT")
        except sqlite3.DatabaseError as exc:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise HoldError("HOLD: failed to persist synthetic acknowledgment") from exc
        return "HOLD: independent read-only reconciliation required"

    def reconcile_fixture(self, request_id, *, evidence_fresh, exact_match):
        """Flags are synthetic: never evidence of an actual exchange fill."""
        if type(evidence_fresh) is not bool or type(exact_match) is not bool:
            raise HoldError("HOLD: invalid synthetic reconciliation flags")
        target = "RECONCILED_HOLD" if evidence_fresh and exact_match else "UNRESOLVED_HOLD"
        try:
            self.db.execute("BEGIN IMMEDIATE")
            cur = self.db.execute(
                "UPDATE review_only_claim SET state=? WHERE account=? AND request_id=?"
                " AND state IN ('UNKNOWN_ACK_HOLD','UNVERIFIED_FILL_HOLD','UNVERIFIED_REJECTION_HOLD')",
                (target, ACCOUNT, request_id),
            )
            if cur.rowcount != 1:
                self.db.execute("ROLLBACK")
                raise HoldError("HOLD: no unresolved fixture acknowledgment")
            self.db.execute("COMMIT")
        except sqlite3.DatabaseError as exc:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise HoldError("HOLD: failed to persist synthetic reconciliation") from exc
        return "HOLD: one-shot is permanently consumed; no replay"
