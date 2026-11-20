"""Standalone one-shot offline entry coordinator listener for disposable CI.

Never deploy as a trading service. No signer, Hyperliquid SDK, outbound
network, production database, credentials or order/close endpoint.
The server exclusively owns the restricted DB connection factories and pins
bot identity from kernel SO_PEERCRED. Same-UID tests are NOT service isolation.
"""
import json
import os
import socket
import stat
import struct

from offline_original_bot_postgres_bridge_ci import OfflineBridgeDecision
from offline_original_bot_socket_bridge_ci import handle_offline_original_entry_socket

_BOTS = frozenset(("daily", "intraday", "aggressive"))


def _check_socket_directory(path, *, ipc_group_gid=None):
    """Validate pre-provisioned mode; never relax a private parent silently."""
    current = os.path.abspath(path)
    while True:
        if stat.S_ISLNK(os.lstat(current).st_mode):
            raise PermissionError("symlinked socket parent")
        upper = os.path.dirname(current)
        if upper == current:
            break
        current = upper
    folder = os.lstat(path)
    expected_mode = 0o700 if ipc_group_gid is None else 0o710
    if (not stat.S_ISDIR(folder.st_mode)
            or folder.st_uid != os.geteuid()
            or stat.S_IMODE(folder.st_mode) != expected_mode
            or (ipc_group_gid is not None and folder.st_gid != ipc_group_gid)):
        raise PermissionError("offline coordinator directory ownership/mode mismatch")


def serve_offline_original_entry_requests(*, socket_path, allowed_uids,
                                          connection_factories,
                                          max_requests=1, ready=None,
                                          timeout=4.0, ipc_group_gid=None):
    """Serve bounded requests from a real Unix listener; never dispatch orders.

    Test harness supplies preconfigured DB factories. No state is created.
    Each client receives only a HOLD / offline-reserved result with explicit
    submit_authorized=False. Dropping a reply NEVER deletes a committed claim.
    """
    if (os.environ.get("ISOLATED_POSTGRES_CI") != "1"
            or os.environ.get("PGDATABASE") != "safety_test"
            or os.environ.get("PGHOST") not in ("localhost", "127.0.0.1")
            or not hasattr(socket, "SO_PEERCRED")):
        raise PermissionError("disposable PostgreSQL CI required")
    if (type(max_requests) is not int or not 1 <= max_requests <= 20
            or type(socket_path) is not str
            or type(allowed_uids) is not dict or not allowed_uids
            or type(connection_factories) is not dict):
        raise ValueError("invalid offline listener configuration")
    if any(type(uid) is not int or uid < 0
           or type(identity) is not tuple or len(identity) != 3
           or any(type(item) is not str for item in identity)
           or identity[0] not in _BOTS
           for uid, identity in allowed_uids.items()):
        raise ValueError("invalid verified UID allowlist")
    if len({identity[0] for identity in allowed_uids.values()}) != len(allowed_uids):
        raise ValueError("one bot must not have multiple UID identities")
    if (set(connection_factories) != {identity[0] for identity in allowed_uids.values()}
            or any(not callable(factory) for factory in connection_factories.values())):
        raise ValueError("server-owned DB login map mismatch")

    # Explicit, root-run disposable CI gate for three genuinely distinct UIDs.
    # Socket group membership grants connectivity only; SO_PEERCRED below
    # verifies each real UID. No bot receives database credentials.
    if ipc_group_gid is not None:
        if (os.environ.get("CI_SOCKET_GROUP_AUDIT") != "1"
                or os.geteuid() != 0
                or type(ipc_group_gid) is not int or ipc_group_gid <= 0
                or len(allowed_uids) != 3
                or any(uid <= 0 for uid in allowed_uids)):
            raise PermissionError("group-gated socket requires disposable root CI")
    folder = os.path.dirname(os.path.abspath(socket_path))
    _check_socket_directory(folder, ipc_group_gid=ipc_group_gid)
    if os.path.lexists(socket_path):
        raise FileExistsError("refuse to replace existing coordinator socket")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(socket_path)
        info = os.lstat(socket_path)
        try:
            if ipc_group_gid is None:
                os.chmod(socket_path, 0o600)  # legacy same-UID CI only
            else:
                os.chown(socket_path, os.geteuid(), ipc_group_gid)
                os.chmod(socket_path, 0o660)
                actual = os.lstat(socket_path)
                if (not stat.S_ISSOCK(actual.st_mode)
                        or actual.st_uid != os.geteuid()
                        or actual.st_gid != ipc_group_gid
                        or stat.S_IMODE(actual.st_mode) != 0o660):
                    raise PermissionError("offline socket group policy not effective")
            listener.listen(max_requests)
            listener.settimeout(timeout)
            if ready is not None:
                ready.set()
            for _ in range(max_requests):
                with listener.accept()[0] as conn:
                    decision = handle_offline_original_entry_socket(
                        conn, allowed_uids, connection_factories,
                    )
                    # The network response is informational, NEVER authority
                    # to submit a trade. Delayed/lost responses preserve claims.
                    if type(decision) is not OfflineBridgeDecision:
                        decision = OfflineBridgeDecision()
                    response = json.dumps({
                        "state": decision.state,
                        "submit_authorized": False,
                    }, separators=(",", ":")).encode("utf-8")
                    try:
                        conn.sendall(struct.pack("!I", len(response)) + response)
                    except OSError:
                        pass
        finally:
            # Never remove another process's replacement socket pathname.
            try:
                current = os.lstat(socket_path)
                if (stat.S_ISSOCK(current.st_mode)
                        and (current.st_dev, current.st_ino) ==
                        (info.st_dev, info.st_ino)):
                    os.unlink(socket_path)
            except FileNotFoundError:
                pass
