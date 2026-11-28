"""CI-only Unix socket client for signer-free original-bot entry requests.

Never import live executors, signing keys, exchange SDK, HTTP or PostgreSQL.
This is a request/ack transport to the disposable safety_test coordinator,
NOT a sender or an authority to place an order. A reservation acknowledgement
NEVER authorizes the bot to submit, retry or infer position ownership.

This prototype does not prove a secure production service identity. A genuine
deployment needs independent OS identities, ACLs and credential revocation.
"""
from __future__ import annotations

import os
import socket
import stat
import struct

from offline_original_bot_intent_adapter import (
    OfflineEntryAckReview,
    prepare_signer_free_entry_handoff_offline,
    review_signer_free_entry_ack_offline,
)

_MAX_REPLY = 1024
_TIMEOUT_SECONDS = 2.0


def _read_exact(peer, amount):
    remaining = amount
    chunks = []
    while remaining:
        part = peer.recv(remaining)
        if not part:
            raise EOFError("coordinator acknowledgement truncated")
        chunks.append(part)
        remaining -= len(part)
    return b"".join(chunks)


def request_offline_entry_via_unix_socket(
    *, socket_path, expected_coordinator_uid, verified_bot,
    trade, rounded_size, pinned_environment, pinned_account,
    pinned_dex="", ipc_group_gid=None,
):
    """Send an unprivileged request to the local CI coordinator, then HOLD.

    Verify the actual server peer UID using Linux SO_PEERCRED, not a value
    returned in a JSON reply. Bot names and account values are deliberately
    absent from the wire message; the *server* pins its allowed identity.
    All errors and ambiguous acknowledgement paths return HOLD.
    """
    def hold(why):
        return OfflineEntryAckReview(reason=why)

    if (os.environ.get("ISOLATED_POSTGRES_CI") != "1"
            or os.environ.get("PGDATABASE") != "safety_test"
            or os.environ.get("PGHOST") not in ("localhost", "127.0.0.1")
            or not hasattr(socket, "SO_PEERCRED")
            or type(expected_coordinator_uid) is not int
            or (expected_coordinator_uid <= 0 and ipc_group_gid is None)
            or expected_coordinator_uid < 0
            or type(socket_path) is not str
            or not os.path.isabs(socket_path)
            or len(os.fsencode(socket_path)) > 100
            or (ipc_group_gid is not None and (
                os.environ.get("CI_SOCKET_GROUP_AUDIT") != "1"
                or type(ipc_group_gid) is not int or ipc_group_gid <= 0))):
        return hold("disposable Linux safety_test coordinator required")

    message = prepare_signer_free_entry_handoff_offline(
        verified_bot=verified_bot, trade=trade,
        rounded_size=rounded_size, pinned_environment=pinned_environment,
        pinned_account=pinned_account, pinned_dex=pinned_dex,
    )
    if message.state != "request_only" or message.submit_authorized:
        return hold("unapproved local action")
    data = message.request_json.encode("utf-8")
    if not 0 < len(data) <= 1024:
        return hold("invalid local entry message length")

    try:
        directory = os.lstat(os.path.dirname(socket_path))
        target = os.lstat(socket_path)
        expected_directory_mode = 0o700 if ipc_group_gid is None else 0o710
        expected_socket_mode = 0o600 if ipc_group_gid is None else 0o660
        if (not stat.S_ISDIR(directory.st_mode)
                or directory.st_uid != expected_coordinator_uid
                or stat.S_IMODE(directory.st_mode) != expected_directory_mode
                or not stat.S_ISSOCK(target.st_mode)
                or target.st_uid != expected_coordinator_uid
                or stat.S_IMODE(target.st_mode) != expected_socket_mode
                or (ipc_group_gid is not None and (
                    directory.st_gid != ipc_group_gid
                    or target.st_gid != ipc_group_gid))):
            return hold("untrusted coordinator socket ownership or permissions")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
            peer.settimeout(_TIMEOUT_SECONDS)
            peer.connect(socket_path)
            creds = peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            _pid, peer_uid, _gid = struct.unpack("3i", creds)
            if peer_uid != expected_coordinator_uid:
                return hold("coordinator OS peer identity mismatch")
            peer.sendall(struct.pack("!I", len(data)) + data)
            # An acknowledgement cannot undo a durable coordinator claim.
            peer.shutdown(socket.SHUT_WR)
            length = struct.unpack("!I", _read_exact(peer, 4))[0]
            if length <= 0 or length > _MAX_REPLY:
                return hold("invalid or oversized coordinator reply")
            reply = _read_exact(peer, length)
    except (OSError, EOFError, ValueError, TypeError, struct.error):
        return hold("coordinator absent, interrupted or ambiguous")

    return review_signer_free_entry_ack_offline(reply_bytes=reply)
