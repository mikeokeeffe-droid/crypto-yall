"""OFFLINE REVIEW of kernel AF_UNIX peer credentials on Linux.

This helper reads Linux SO_PEERCRED from an already-connected Unix stream
socket. It is NOT a listener, gateway, approval mechanism or network client.
It never creates sockets, opens a path, sends data, or makes HTTP requests.

A future service still needs a private protected socket path, authorization
bound to a reviewed service process/cgroup, replay protection, and enforceable
network isolation. Same UID is NOT enough to authenticate one process.
"""
import socket
import struct
from collections import namedtuple

from readonly_connection_review.testnet_egress_policy_review_offline import PolicyHold

PeerCredentials = namedtuple("PeerCredentials", "pid uid gid")
_UCRED_SIZE = struct.calcsize("=iii")


def kernel_unix_peer_credentials(connection):
    """Obtain kernel-provided credentials; never accept caller-supplied IDs."""
    if (not hasattr(socket, "SO_PEERCRED")
            or type(connection) is not socket.socket
            or connection.family != socket.AF_UNIX
            or (connection.type & 15) != socket.SOCK_STREAM):
        raise PolicyHold("kernel Unix stream credentials unavailable")
    try:
        raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _UCRED_SIZE)
        if len(raw) != _UCRED_SIZE:
            raise PolicyHold("invalid kernel credential size")
        pid, uid, gid = struct.unpack("=iii", raw)
    except (OSError, ValueError, struct.error):
        raise PolicyHold("kernel Unix peer credentials could not be verified") from None
    if pid <= 1 or uid < 0 or gid < 0:
        raise PolicyHold("invalid kernel Unix peer identity")
    return PeerCredentials(pid=pid, uid=uid, gid=gid)


def review_kernel_peer_offline(connection, admission, *, approved_review_lease, nonce):
    """Feed actual Linux peer values to the purely offline admission fixture.

    The admission fixture is NOT suitable for production; its expected IDs
    and test nonce are provided by the caller. NO network authority results.
    """
    creds = kernel_unix_peer_credentials(connection)
    return admission.inspect_synthetic_peer(
        kernel_uid=creds.uid, kernel_gid=creds.gid, kernel_pid=creds.pid,
        approved_review_lease=approved_review_lease, nonce=nonce
    )
