"""Offline-only Unix socket boundary for original-bot CI PostgreSQL intents.

No live SDK, trading signer, TCP listener, or general-purpose SQL endpoint.
The kernel-provided peer UID is mapped through a caller-provided test allowlist.
Mapping multiple bots onto a single Unix UID in tests is NOT OS isolation;
production requires distinct authenticated service identities.
"""
import json
import os
import socket
import struct

from offline_framed_unix_coordinator_fixture import MAX_FRAME, _read_exact
from offline_unix_peer_identity_fixture import offline_peer_identity
from offline_original_bot_postgres_bridge_ci import (
    OfflineBridgeDecision, record_offline_original_entry,
)

_FIELDS = frozenset(("operation", "action", "side", "hl_coin", "rounded_size"))


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def handle_offline_original_entry_socket(connection, allowed_uids,
                                         connection_factories):
    """Request only a CI-only reservation; always return no submit authority.

    The client cannot choose bot, account, environment, database role or SQL
    function. The mapping and DB factories must be pinned by the *server*.
    This disposable harness does not deploy a production coordinator.
    """
    held = OfflineBridgeDecision()
    if (os.environ.get("ISOLATED_POSTGRES_CI") != "1"
            or os.environ.get("PGDATABASE") != "safety_test"
            or os.environ.get("PGHOST") not in ("localhost", "127.0.0.1")
            or not hasattr(socket, "SO_PEERCRED")
            or connection.family != socket.AF_UNIX):
        return held
    try:
        connection.settimeout(1)
        identity = offline_peer_identity(connection, allowed_uids)
        if identity is None:
            return held
        bot, environment, account = identity
        if (type(bot) is not str or type(environment) is not str
                or type(account) is not str
                or type(connection_factories) is not dict):
            return held
        factory = connection_factories.get(bot)
        if not callable(factory):
            return held
        length = struct.unpack("!I", _read_exact(connection, 4))[0]
        if length <= 0 or length > MAX_FRAME:
            return held
        payload = json.loads(
            _read_exact(connection, length).decode("utf-8"),
            object_pairs_hook=_unique_pairs,
        )
        if (type(payload) is not dict or set(payload) != _FIELDS
                or any(type(value) is not str for value in payload.values())
                or payload["operation"] != "request_entry"):
            return held
        trade = {key: payload[key] for key in ("action", "side", "hl_coin")}
        return record_offline_original_entry(
            connection_factory=factory,
            verified_bot=bot,
            trade=trade,
            rounded_size=payload["rounded_size"],
            pinned_environment=environment,
            pinned_account=account,
        )
    except Exception:
        return held
