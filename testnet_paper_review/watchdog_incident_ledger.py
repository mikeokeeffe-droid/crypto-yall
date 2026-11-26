"""Persistent local watchdog incident review, separate from trading journals.

No network, secrets, notification transport or order authority. The caller
must provide an existing private state directory on the dedicated host.
A crash after begin() and before finish() remains an unresolved incident
at the next invocation. No reset or automatic incident clearance exists.
"""
import os
from pathlib import Path
import sqlite3
import stat

class WatchdogStateHold(RuntimeError):
    pass

class WatchdogLedger:
    def __init__(self, directory):
        root = Path(directory)
        if (not root.is_absolute() or root.is_symlink() or not root.is_dir()
                or root.stat().st_uid != os.getuid()
                or stat.S_IMODE(root.stat().st_mode) != 0o700):
            raise WatchdogStateHold("HOLD: unsafe watchdog state directory")
        path = root / "watchdog-incidents.sqlite3"
        if path.is_symlink():
            raise WatchdogStateHold("HOLD: redirected watchdog ledger")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        if (path.is_symlink() or not path.is_file()
                or path.stat().st_uid != os.getuid()
                or stat.S_IMODE(path.stat().st_mode) != 0o600):
            raise WatchdogStateHold("HOLD: unsafe watchdog ledger")
        self.db = sqlite3.connect(path.as_uri()+"?mode=rw", uri=True,
                                  isolation_level=None, timeout=3)
        try:
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA journal_mode=DELETE")
            self.db.execute("CREATE TABLE IF NOT EXISTS watchdog ("
                            "id INTEGER PRIMARY KEY CHECK(id=1), "
                            "pending INTEGER NOT NULL CHECK(pending IN (0,1)), "
                            "incident TEXT)")
            self.db.execute("INSERT OR IGNORE INTO watchdog VALUES(1,0,NULL)")
            if self.db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise WatchdogStateHold("HOLD: corrupt watchdog ledger")
        except Exception:
            self.db.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def view(self):
        rows = self.db.execute("SELECT pending,incident FROM watchdog WHERE id=1").fetchall()
        if len(rows) != 1 or rows[0][0] not in (0,1):
            raise WatchdogStateHold("HOLD: invalid watchdog state")
        return rows[0]

    def begin(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            pending, incident = self.view()
            if pending:
                incident = incident or "INTERRUPTED_OR_COMPETING_WATCH"
            self.db.execute("UPDATE watchdog SET pending=1, incident=? WHERE id=1",(incident,))
            self.db.execute("COMMIT")
            return incident
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def finish(self, outcome):
        if outcome not in ("FLAT","BRACKET_OBSERVED","UNVERIFIED","UNKNOWN_ACK",
                           "MISSING_STOP","FOREIGN_EXPOSURE","EMERGENCY_ATTEMPT",
                           "READ_FAILED","STALE_OBSERVATION"):
            outcome = "UNVERIFIED"
        self.db.execute("BEGIN IMMEDIATE")
        try:
            pending, incident = self.view()
            if not pending:
                incident = incident or "UNEXPECTED_COMPLETION"
            if outcome not in ("FLAT","BRACKET_OBSERVED"):
                incident = incident or outcome
            self.db.execute("UPDATE watchdog SET pending=0, incident=? WHERE id=1",(incident,))
            self.db.execute("COMMIT")
            return incident
        except Exception:
            self.db.execute("ROLLBACK")
            raise
