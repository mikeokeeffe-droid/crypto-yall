"""Review-only one-shot AF_UNIX request protocol: REAL LOCAL IPC, NO NETWORK.

This uses an already-connected Unix stream socket and the offline peer and
process-provenance checks. It never binds/listens on a socket pathname,
starts a process, opens an HTTP connection, contacts any exchange, or uses
credentials. Its successful reply is labeled MOCK, not an account balance.

NOT DEPLOYABLE. The caller supplies expected identity and an approval test
fixture; a real gateway needs host-trusted identity binding, socket path
permissions, replay/lifetime handling, and independently verified egress.
"""
import json
import socket

from readonly_connection_review.offline_gateway_integration_review import (
    review_offline_identity_to_frames,
)
from readonly_connection_review.testnet_egress_policy_review_offline import (
    PolicyHold,
)

# No free-form request fields, URLs, accounts, tokens or trading instructions.
REQUEST = b"READ_TESTNET_ACCOUNT_COUNTS_OFFLINE_V1\n"
MAX_REQUEST_BYTES = len(REQUEST)
SOCKET_TIMEOUT_SECONDS = 2


def _receive_exact_review_command(connection):
    """Read one command bounded by length and time; reject extra bytes."""
    if type(connection) is not socket.socket or connection.family != socket.AF_UNIX:
        raise PolicyHold("local Unix socket required")
    old_timeout = connection.gettimeout()
    try:
        connection.settimeout(SOCKET_TIMEOUT_SECONDS)
        try:
            command = connection.recv(MAX_REQUEST_BYTES + 1)
        except (OSError, TimeoutError):
            raise PolicyHold("local review command unavailable") from None
        if command != REQUEST:
            raise PolicyHold("unapproved or incomplete local review command")
    finally:
        connection.settimeout(old_timeout)


def handle_connected_review_socket(
    connection, *,
    expected_uid, expected_gid, expected_provenance,
    approved_review_lease, test_nonce, policy, clock=None,
):
    """Respond only to a bounded, fixed command on preconnected AF_UNIX.

    This returns MOCK counts, not real API data. A caller-supplied identity or
    approval is inherently untrusted; all parameters are review fixtures.
    Never use this function in a network-enabled gateway.
    """
    frames = review_offline_identity_to_frames(
        connection,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        expected_provenance=expected_provenance,
        approved_review_lease=approved_review_lease,
        test_nonce=test_nonce, policy=policy, clock=clock,
    )
    if len(frames) != 2:
        raise PolicyHold("synthetic review sequence incomplete")
    _receive_exact_review_command(connection)
    response = (
        json.dumps(
            {
                "status": "MOCK_OFFLINE_REVIEW_ONLY",
                "positions": 0, "open_orders": 0,
                "api_connected": False, "trading_enabled": False,
            },
            separators=(",", ":"), sort_keys=True
        ) + "\n"
    ).encode("ascii")
    old_timeout = connection.gettimeout()
    try:
        connection.settimeout(SOCKET_TIMEOUT_SECONDS)
        try:
            connection.sendall(response)
        except (OSError, TimeoutError):
            raise PolicyHold("local mock response failed") from None
    finally:
        connection.settimeout(old_timeout)
    return len(frames)
