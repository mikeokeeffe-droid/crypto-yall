"""Offline-only Unix coordinator listener.

This is an integration fixture, NOT a deployable trading service. It has no
signer, exchange client, outbound network, order or close capability. Callers
must provision distinct worker UIDs and a private parent directory separately.
"""
import os
import socket
import stat
from offline_socket_journal_bridge_fixture import handle_offline_journal_socket
from offline_persistent_replay_ledger import OfflinePersistentReplayLedger
from offline_sender_restart_journal import OfflineRestartJournal
from offline_shared_sender_prototype import OfflineSharedSender

def serve_offline_socket_once(socket_path,allowed_uids,replay_path,journal_path,
                              ready=None,timeout=2):
    """Accept exactly one request; never recreate missing state or unlink paths."""
    if not isinstance(allowed_uids,dict) or not allowed_uids:
        raise ValueError("explicit UID allowlist required")
    if any(type(uid) is not int or uid < 0 or
           type(identity) is not tuple or len(identity) != 3 or
           any(type(value) is not str or not value for value in identity)
           for uid,identity in allowed_uids.items()):
        raise ValueError("invalid UID identity mapping")
    if any(OfflineSharedSender._scope(identity[1],identity[2],"","SOL") is None
           for identity in allowed_uids.values()):
        raise ValueError("invalid bot environment or account scope")
    bots=[identity[0] for identity in allowed_uids.values()]
    if len(set(bots)) != len(bots):
        raise ValueError("each bot must have its own Linux UID")
    if any(bot not in ("daily","intraday","aggressive") for bot in bots):
        raise ValueError("unknown bot identity")
    parent=os.path.dirname(os.path.abspath(socket_path))
    if os.path.islink(parent) or not stat.S_ISDIR(os.stat(parent).st_mode):
        raise ValueError("invalid socket directory")
    # Private coordinator-owned directory; a real service needs managed ACLs.
    if os.lstat(parent).st_uid != os.geteuid():
        raise PermissionError("socket parent must belong to coordinator")
    if os.stat(parent).st_mode & 0o022:
        raise PermissionError("socket parent must not be group/world writable")
    if os.path.lexists(socket_path):
        raise FileExistsError("refuse to overwrite existing socket path")
    for state_path in (journal_path,replay_path):
        state_parent=os.path.dirname(os.path.abspath(state_path))
        parent_info=os.lstat(state_parent)
        if not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_mode & 0o022:
            raise PermissionError("offline state parent must be a protected directory")
        if parent_info.st_uid != os.geteuid():
            raise PermissionError("offline state parent must belong to coordinator")
    for state_path in (journal_path,replay_path):
        state=os.lstat(state_path)
        if not stat.S_ISREG(state.st_mode) or state.st_mode & 0o077:
            raise PermissionError("offline state file must be private regular file")
        if state.st_uid != os.geteuid():
            raise PermissionError("offline state file must belong to coordinator")
    OfflineRestartJournal(journal_path)
    OfflinePersistentReplayLedger(replay_path)
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
        listener.bind(socket_path)
        try:
            os.chmod(socket_path,0o600)
            bound_inode=os.lstat(socket_path).st_ino
            listener.listen(1)
            listener.settimeout(timeout)
            if ready is not None:
                ready.set()
            connection,_=listener.accept()
            with connection:
                return handle_offline_journal_socket(
                    connection,allowed_uids,replay_path,journal_path)
        finally:
            # Only remove our own socket inode, not a replacement path.
            try:
                if os.path.exists(socket_path) and os.path.islink(socket_path) is False and os.lstat(socket_path).st_ino==bound_inode:
                    os.unlink(socket_path)
            except OSError:
                pass
