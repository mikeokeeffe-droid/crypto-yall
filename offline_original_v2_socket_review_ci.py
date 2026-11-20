"""CI-only Unix socket V2 review handler; no order protocol or signer.

The client supplies ONLY review action/size/leverage. Linux SO_PEERCRED and
the SERVER'S allowlist determine bot, account, environment and database role.
A valid request can record one immutable, non-executable safety_test row.
No close, order, dispatch, release, signer, HTTP or live database access.
"""
import json
import os
import socket
import struct

from offline_framed_unix_coordinator_fixture import _read_exact
from offline_unix_peer_identity_fixture import offline_peer_identity
from offline_leverage_bound_entry_draft_ci import OfflineLeverageDraft
from offline_original_v2_review_bridge_ci import (
    OfflineV2ReviewAdmission, record_v2_draft_for_offline_review,
)

MAX_V2_FRAME = 1024


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate review field")
        result[key] = value
    return result


def handle_offline_v2_review_socket(conn, allowed_uids, connection_factories):
    """No submit authorization even if review row is successfully committed."""
    held = OfflineV2ReviewAdmission()
    if (os.environ.get("ISOLATED_POSTGRES_CI") != "1"
            or os.environ.get("PGDATABASE") != "safety_test"
            or os.environ.get("PGHOST") not in ("localhost", "127.0.0.1")
            or os.environ.get("CI_V2_REVIEW_AUDIT") != "1"
            or not hasattr(socket, "SO_PEERCRED")
            or conn.family != socket.AF_UNIX
            or type(connection_factories) is not dict):
        return held
    try:
        conn.settimeout(1)
        identity = offline_peer_identity(conn, allowed_uids)
        if identity is None:
            return held
        bot, environment, account = identity
        factory = connection_factories.get(bot)
        if not callable(factory):
            return held
        n = struct.unpack("!I", _read_exact(conn, 4))[0]
        if not 0 < n <= MAX_V2_FRAME:
            return held
        raw = _read_exact(conn, n)
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
        if (type(payload) is not dict
                or set(payload) != {
                    "operation", "action", "side", "hl_coin",
                    "rounded_size", "requested_leverage",
                    "cross_margin_requested",
                }):
            return held
        # The socket cannot set bot/account/environment, fake authority,
        # a CLOID, SQL principal, or a requested token/fence.
        review = OfflineLeverageDraft(
            state="review_only",
            review_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
        # The review token is made by a SQL function, not by the client.
        # A lost response is ambiguous; do not automatically reissue.
        import uuid
        return record_v2_draft_for_offline_review(
            connection_factory=factory, verified_bot=bot,
            pinned_environment=environment, pinned_account=account,
            draft=review, request_id=uuid.uuid4(),
        )
    except (OSError, EOFError, ValueError, UnicodeError, TypeError,
            struct.error):
        return held
