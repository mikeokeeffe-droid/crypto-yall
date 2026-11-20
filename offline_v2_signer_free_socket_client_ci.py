"""CI-only, signer-free V2 review client. No trading/order authority.

Sends the previously built leverage+size *review* draft to a disposable
Unix-socket coordinator, and verifies the coordinator's Linux SO_PEERCRED UID
and strict directory/socket ownership. Neither a successful review nor a
server ACK authorizes an order, marks leverage applied, or confirms a fill.

No bot/exchange SDK, HTTP, PostgreSQL, private key, secret, retry loop, or
production service. The kernel-authenticated bot identity is assigned by
the SERVER, never by a caller-controlled wire field.
"""
from dataclasses import dataclass
import json
import os
import socket
import stat
import struct

from offline_leverage_bound_entry_draft_ci import OfflineLeverageDraft

_MAX_FRAME = 1024


@dataclass(frozen=True)
class OfflineV2ClientAck:
    state: str = "hold"
    reason: str = "no trusted review acknowledgement"
    review_recorded: bool = False
    submit_authorized: bool = False
    leverage_applied: bool = False


def _no_duplicates(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError("duplicate field")
        result[k] = v
    return result


def _read_exact(sock, count):
    parts = []
    while count:
        part = sock.recv(count)
        if not part:
            raise EOFError("truncated review ACK")
        parts.append(part)
        count -= len(part)
    return b"".join(parts)


def request_v2_review_via_unix_socket_offline(
    *, socket_path, expected_coordinator_uid, draft, ipc_group_gid=None,
):
    """Never return trade permission. Lost acknowledgements HOLD, no retry."""
    def hold(reason):
        return OfflineV2ClientAck(reason=reason)

    if (os.environ.get("ISOLATED_POSTGRES_CI") != "1"
            or os.environ.get("PGDATABASE") != "safety_test"
            or os.environ.get("PGHOST") not in ("localhost", "127.0.0.1")
            or os.environ.get("CI_V2_REVIEW_AUDIT") != "1"
            or not hasattr(socket, "SO_PEERCRED")
            or type(socket_path) is not str
            or not os.path.isabs(socket_path)
            or len(os.fsencode(socket_path)) > 100
            or type(expected_coordinator_uid) is not int
            or expected_coordinator_uid < 0
            or (ipc_group_gid is None and expected_coordinator_uid == 0)
            or (ipc_group_gid is not None and (
                type(ipc_group_gid) is not int or ipc_group_gid <= 0
                or expected_coordinator_uid != 0))
            or type(draft) is not OfflineLeverageDraft
            or draft.state != "review_only"
            or draft.submit_authorized is not False
            or draft.leverage_applied is not False
            or type(draft.review_json) is not str):
        return hold("disposable V2 review client preconditions failed")

    try:
        data = draft.review_json.encode("utf-8")
        if not 0 < len(data) <= _MAX_FRAME:
            return hold("invalid review frame size")
        msg = json.loads(data, object_pairs_hook=_no_duplicates)
        if (type(msg) is not dict
                or set(msg) != {
                    "operation", "action", "side", "hl_coin",
                    "rounded_size", "requested_leverage",
                    "cross_margin_requested",
                }
                or msg["operation"] != "review_entry_leverage_v2"):
            return hold("not a V2 review message")
        # Reject client-invented bot/account/environment/authorization fields
        # even if the server would also reject them. Never send key material.
        folder = os.lstat(os.path.dirname(socket_path))
        target = os.lstat(socket_path)
        folder_mode = 0o700 if ipc_group_gid is None else 0o710
        socket_mode = 0o600 if ipc_group_gid is None else 0o660
        if (not stat.S_ISDIR(folder.st_mode)
                or folder.st_uid != expected_coordinator_uid
                or stat.S_IMODE(folder.st_mode) != folder_mode
                or not stat.S_ISSOCK(target.st_mode)
                or target.st_uid != expected_coordinator_uid
                or stat.S_IMODE(target.st_mode) != socket_mode
                or (ipc_group_gid is not None
                    and (folder.st_gid != ipc_group_gid
                         or target.st_gid != ipc_group_gid))):
            return hold("untrusted socket ownership or access mode")

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            sock.connect(socket_path)
            raw = sock.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED,
                struct.calcsize("3i"),
            )
            pid, uid, _gid = struct.unpack("3i", raw)
            if pid <= 0 or uid != expected_coordinator_uid:
                return hold("coordinator peer UID mismatch")
            sock.sendall(struct.pack("!I", len(data)) + data)
            sock.shutdown(socket.SHUT_WR)
            n = struct.unpack("!I", _read_exact(sock, 4))[0]
            if not 0 < n <= _MAX_FRAME:
                return hold("invalid V2 review ACK length")
            raw_ack = _read_exact(sock, n)
        ack = json.loads(raw_ack, object_pairs_hook=_no_duplicates)
        if (type(ack) is not dict
                or set(ack) != {
                    "state", "submit_authorized", "leverage_applied"
                }
                or ack["submit_authorized"] is not False
                or ack["leverage_applied"] is not False
                or type(ack["state"]) is not str
                or ack["state"] not in ("recorded_review_only", "hold")):
            return hold("untrusted V2 ACK or false trading authority")
        return OfflineV2ClientAck(
            state=ack["state"],
            reason="review recorded only; never authorizes an order"
            if ack["state"] == "recorded_review_only"
            else "coordinator HOLD; no review accepted",
            review_recorded=ack["state"] == "recorded_review_only",
        )
    except (OSError, EOFError, ValueError, TypeError, UnicodeError,
            struct.error):
        return hold("review coordinator unavailable or ACK ambiguous")
