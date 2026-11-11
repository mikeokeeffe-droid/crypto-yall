"""Disposable, network-free Unix-socket handoff for signer-free Info fixtures.

The only data source is a caller-supplied synthetic snapshot. There is NO
Hyperliquid HTTP, exchange client, signer, database, token, production service
or trading authorization. A peer UID verifies a CI socket process, NOT the
authenticity of the underlying synthetic exchange data or position ownership.

Do not deploy as a production read-only collector. The 0700 socket parent
means these tests are same-UID only; distinct workload identities need a
separately reviewed credential and filesystem/IPC policy.
"""
from dataclasses import dataclass
import json
import os
import socket
import stat
import struct

from offline_signer_free_info_fixture_ci import (
    OfflineSignerFreeInfoScope, make_signer_free_info_fixture,
)

_MAX_BYTES = 65536
_MAX_AGE_MS = 30000
_REQUEST = b'{"operation":"read_info_fixture"}'


@dataclass(frozen=True)
class OfflineInfoServiceReview:
    state: str = "hold"
    reason: str = "offline info service unavailable"
    view: object | None = None
    origin_authenticated: bool = False
    history_complete: bool = False
    ownership_verified: bool = False
    submit_authorized: bool = False


def _pairs_unique(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("duplicate JSON key")
        output[key] = value
    return output


def _receive_exact(sock, count):
    result = []
    while count:
        part = sock.recv(count)
        if not part:
            raise EOFError("interrupted CI snapshot frame")
        result.append(part)
        count -= len(part)
    return b"".join(result)


def _receive_frame(sock):
    count = struct.unpack("!I", _receive_exact(sock, 4))[0]
    if not 0 < count <= _MAX_BYTES:
        raise ValueError("unbounded or empty fixture frame")
    return _receive_exact(sock, count)


def _send_frame(sock, data):
    if type(data) is not bytes or not 0 < len(data) <= _MAX_BYTES:
        raise ValueError("invalid fixture frame")
    sock.sendall(struct.pack("!I", len(data)) + data)


def _socket_path_is_private(path, expected_uid, *, bound=False):
    if (type(path) is not str or not os.path.isabs(path)
            or len(os.fsencode(path)) > 100
            or type(expected_uid) is not int or expected_uid < 0):
        return False
    directory = os.lstat(os.path.dirname(path))
    if (not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != expected_uid
            or stat.S_IMODE(directory.st_mode) != 0o700):
        return False
    if bound:
        sock = os.lstat(path)
        if (not stat.S_ISSOCK(sock.st_mode)
                or sock.st_uid != expected_uid
                or stat.S_IMODE(sock.st_mode) != 0o600):
            return False
    return True


def serve_one_offline_info_fixture(*, socket_path, allowed_peer_uid,
                                   scope, snapshot, captured_at_ms,
                                   ready=None):
    """A single test-only read service using an independent local process."""
    if (os.environ.get("OFFLINE_SNAPSHOT_CI") != "1"
            or not hasattr(socket, "SO_PEERCRED")
            or type(scope) is not OfflineSignerFreeInfoScope
            or type(allowed_peer_uid) is not int or allowed_peer_uid < 0
            or type(captured_at_ms) is not int or captured_at_ms <= 0
            or make_signer_free_info_fixture(
                scope=scope, snapshot=snapshot,
            ) is None
            or not _socket_path_is_private(socket_path, os.getuid())
            or os.path.lexists(socket_path)):
        raise PermissionError("disposable, validated private fixture service required")

    packet = {
        "state": "fixture_only",
        "origin": "fixture",
        "scope": {"environment": scope.environment, "account": scope.account},
        "captured_at_ms": captured_at_ms,
        "snapshot": snapshot,
        "origin_authenticated": False,
        "history_complete": False,
        "ownership_verified": False,
        "submit_authorized": False,
    }
    response = json.dumps(packet, separators=(",", ":"), allow_nan=False).encode()
    if len(response) > _MAX_BYTES:
        raise ValueError("oversized synthetic snapshot")
    hold = b'{"state":"hold","submit_authorized":false}'
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(socket_path)
        original = os.lstat(socket_path)
        try:
            os.chmod(socket_path, 0o600)
            server.listen(1)
            server.settimeout(4.0)
            if ready is not None:
                ready.set()
            with server.accept()[0] as conn:
                conn.settimeout(2.0)
                creds = conn.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, 12,
                )
                _pid, uid, _gid = struct.unpack("3i", creds)
                approved = uid == allowed_peer_uid
                if approved:
                    try:
                        wire = _receive_frame(conn)
                        approved = wire == _REQUEST
                    except (OSError, EOFError, ValueError, struct.error):
                        approved = False
                try:
                    _send_frame(conn, response if approved else hold)
                except OSError:
                    # Unknown/lost acknowledgement cannot authorize anything.
                    pass
        finally:
            try:
                current = os.lstat(socket_path)
                if (stat.S_ISSOCK(current.st_mode)
                        and (current.st_dev, current.st_ino) ==
                        (original.st_dev, original.st_ino)):
                    os.unlink(socket_path)
            except FileNotFoundError:
                pass


def request_offline_info_fixture(*, socket_path, expected_server_uid,
                                 scope, now_ms):
    """Read one pinned synthetic snapshot; HOLD on every ambiguous outcome."""
    def hold(reason):
        return OfflineInfoServiceReview(reason=reason)

    if (os.environ.get("OFFLINE_SNAPSHOT_CI") != "1"
            or not hasattr(socket, "SO_PEERCRED")
            or type(scope) is not OfflineSignerFreeInfoScope
            or type(now_ms) is not int or now_ms <= 0
            or not _socket_path_is_private(
                socket_path, expected_server_uid, bound=True,
            )):
        return hold("invalid or absent private offline info service")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(2.0)
            conn.connect(socket_path)
            credentials = conn.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, 12,
            )
            _pid, uid, _gid = struct.unpack("3i", credentials)
            if uid != expected_server_uid:
                return hold("local service OS identity mismatch")
            _send_frame(conn, _REQUEST)
            raw = _receive_frame(conn)
        packet = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs_unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(
                                ValueError("nonfinite JSON constant")
                            ))
    except (OSError, EOFError, UnicodeError, ValueError, TypeError, struct.error):
        return hold("unavailable or malformed offline info reply")

    if (type(packet) is not dict or packet.get("state") != "fixture_only"
            or set(packet) != {
                "state", "origin", "scope", "captured_at_ms", "snapshot",
                "origin_authenticated", "history_complete",
                "ownership_verified", "submit_authorized",
            } or packet["origin"] != "fixture"
            or packet["origin_authenticated"] is not False
            or packet["history_complete"] is not False
            or packet["ownership_verified"] is not False
            or packet["submit_authorized"] is not False
            or packet["scope"] != {
                "environment": scope.environment, "account": scope.account,
            }):
        return hold("fixture response attempted to change scope or authority")
    captured = packet["captured_at_ms"]
    if (type(captured) is not int or captured <= 0 or captured > now_ms
            or now_ms - captured > _MAX_AGE_MS):
        return hold("stale, future or malformed synthetic snapshot")
    view = make_signer_free_info_fixture(scope=scope, snapshot=packet["snapshot"])
    if view is None:
        return hold("invalid synthetic information schema")
    return OfflineInfoServiceReview(
        state="fixture_only",
        reason="separate local fixture service reachable; real exchange provenance "
               "and historical coverage unverified",
        view=view,
    )
