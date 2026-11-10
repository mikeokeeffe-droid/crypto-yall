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

def serve_offline_socket_once(socket_path,allowed_uids,replay_path,journal_path,
                              ready=None,timeout=2):
    """Accept exactly one request; never recreate missing state or unlink paths."""
    if not isinstance(allowed_uids,dict) or not allowed_uids:
        raise ValueError("explicit UID allowlist required")
    parent=os.path.dirname(os.path.abspath(socket_path))
    if os.path.islink(parent) or not stat.S_ISDIR(os.stat(parent).st_mode):
        raise ValueError("invalid socket directory")
    # Private coordinator-owned directory; a real service needs managed ACLs.
    if os.stat(parent).st_mode & 0o022:
        raise PermissionError("socket parent must not be group/world writable")
    if os.path.lexists(socket_path):
        raise FileExistsError("refuse to overwrite existing socket path")
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
