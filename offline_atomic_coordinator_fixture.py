"""Disposable atomic replay + scope reservation prototype. NEVER authorizes trading."""
import os
import sqlite3
import stat
import uuid
from pathlib import Path
from offline_shared_sender_prototype import OfflineSharedSender

_SCHEMA = """
CREATE TABLE replay_nonces(
 principal TEXT NOT NULL, nonce TEXT NOT NULL,
 PRIMARY KEY(principal,nonce));
CREATE TABLE claims(
 environment TEXT NOT NULL, account TEXT NOT NULL, dex TEXT NOT NULL,
 coin TEXT NOT NULL, bot TEXT NOT NULL, token TEXT NOT NULL UNIQUE,
 cloid TEXT NOT NULL UNIQUE, fence INTEGER NOT NULL UNIQUE,
 state TEXT NOT NULL CHECK(state IN ('reserved','dispatch_unknown')),
 PRIMARY KEY(environment,account,dex,coin));
CREATE TABLE metadata(schema_version INTEGER NOT NULL, next_fence INTEGER NOT NULL);
INSERT INTO metadata VALUES(1,1);
"""

class OfflineAtomicCoordinator:
    """Test fixture only: one local SQLite file; no SDK, signer or network."""

    def __init__(self,path,*,create=False):
        self.path=str(path)
        if create:
            if os.path.lexists(self.path):
                raise FileExistsError("atomic fixture already exists")
            with sqlite3.connect(self.path) as db:
                db.executescript(_SCHEMA)
            os.chmod(self.path,0o600)
        # Check the containing directory before trusting a database pathname.
        # This is a fixture-level check, not race-free production path handling.
        parent=os.path.dirname(os.path.abspath(self.path))
        parent_info=os.lstat(parent)
        if not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_mode & 0o022:
            raise PermissionError("atomic fixture parent must be protected directory")
        if parent_info.st_uid!=os.geteuid():
            raise PermissionError("atomic fixture parent must belong to coordinator")
        current=parent
        while True:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise PermissionError("symlinked atomic fixture ancestor")
            upper=os.path.dirname(current)
            if upper==current:
                break
            current=upper
        if not os.path.lexists(self.path):
            raise FileNotFoundError("atomic fixture missing")
        file_info=os.lstat(self.path)
        if not stat.S_ISREG(file_info.st_mode) or file_info.st_mode & 0o077:
            raise PermissionError("atomic fixture must be a private regular file")
        if file_info.st_uid!=os.geteuid():
            raise PermissionError("atomic fixture must belong to coordinator")
        with self._connect() as db:
            if db.execute("PRAGMA integrity_check").fetchone()!=("ok",):
                raise sqlite3.DatabaseError("damaged atomic fixture")
            version=db.execute("SELECT schema_version,next_fence FROM metadata").fetchall()
            if len(version)!=1 or version[0][0]!=1 or version[0][1]<1:
                raise sqlite3.DatabaseError("invalid atomic fixture metadata")
            expected={
                "replay_nonces":("principal","nonce"),
                "claims":("environment","account","dex","coin","bot",
                          "token","cloid","fence","state"),
                "metadata":("schema_version","next_fence"),
            }
            for name,columns in expected.items():
                actual=tuple(row[1] for row in db.execute("PRAGMA table_info("+name+")"))
                if actual!=columns:
                    raise sqlite3.DatabaseError("invalid atomic fixture schema: "+name)
            # Column names alone are insufficient: a recreated table without
            # uniqueness constraints would permit duplicate replay or claims.
            for table,unique_columns in (
                ("replay_nonces",{"principal","nonce"}),
                ("claims",{"environment","account","dex","coin"})):
                indexes=db.execute("PRAGMA index_list("+table+")").fetchall()
                unique_sets=[
                    {row[2] for row in db.execute("PRAGMA index_info("+index[1]+")")}
                    for index in indexes if index[2]
                ]
                if unique_columns not in unique_sets:
                    raise sqlite3.DatabaseError("missing atomic fixture uniqueness: "+table)

    def _connect(self):
        uri=Path(self.path).absolute().as_uri()+"?mode=rw"
        return sqlite3.connect(uri,uri=True,timeout=5,isolation_level=None)

    def reserve(self,*,principal,nonce,bot,environment,account,dex,coin,
                inject_failure=None):
        scope=OfflineSharedSender._scope(environment,account,dex,coin)
        if (scope is None or bot not in ("daily","intraday","aggressive")
            or type(principal) is not str or not principal
            or type(nonce) is not str or not 1<=len(nonce)<=128):
            return ("hold",False)
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    db.execute("INSERT INTO replay_nonces VALUES(?,?)",(principal,nonce))
                    if inject_failure=="after_nonce":
                        raise RuntimeError("simulated crash before claim")
                    fence=db.execute("SELECT next_fence FROM metadata").fetchone()[0]
                    token,cloid=str(uuid.uuid4()),"0x"+uuid.uuid4().hex
                    db.execute("INSERT INTO claims VALUES(?,?,?,?,?,?,?,?,?)",
                               (*scope,bot,token,cloid,fence,"reserved"))
                    db.execute("UPDATE metadata SET next_fence=?",(fence+1,))
                    if inject_failure=="after_claim":
                        raise RuntimeError("simulated crash before commit")
                    db.commit()
                    return ("reserved_offline_only",False)
                except Exception:
                    db.rollback()
                    return ("hold",False)
        except (sqlite3.Error,OSError):
            return ("hold",False)

    def inspect(self,*,environment,account,dex,coin):
        scope=OfflineSharedSender._scope(environment,account,dex,coin)
        if scope is None:
            return None
        with self._connect() as db:
            return db.execute(
                "SELECT bot,token,cloid,fence,state FROM claims "
                "WHERE environment=? AND account=? AND dex=? AND coin=?",scope).fetchone()
