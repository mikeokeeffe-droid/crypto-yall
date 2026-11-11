"""Offline-only atomic socket bridge; no live order, close or signing authority.

Distinct from the legacy two-database bridge. Test harness supplies the
pre-created atomic database; this function never creates state.
"""
import json
import os
import socket
import struct
from offline_atomic_coordinator_fixture import OfflineAtomicCoordinator
from offline_unix_peer_identity_fixture import offline_peer_identity
from offline_framed_unix_coordinator_fixture import MAX_FRAME,_read_exact
from offline_shared_sender_prototype import OfflineSharedSender

def handle_offline_atomic_socket(connection,allowed_uids,coordinator):
    """Require a coordinator pinned at service startup; never reopen by path."""
    try:
        connection.settimeout(1)
        identity=offline_peer_identity(connection,allowed_uids)
        if identity is None:
            return ("hold",False)
        size=struct.unpack("!I",_read_exact(connection,4))[0]
        if not 0<size<=MAX_FRAME:
            return ("hold",False)
        payload=json.loads(_read_exact(connection,size).decode("utf-8"))
        required={"operation","requested_bot","environment","account",
                  "dex","coin","nonce"}
        if type(payload) is not dict or set(payload)!=required:
            return ("hold",False)
        if any(type(value) is not str for value in payload.values()):
            return ("hold",False)
        bot,environment,account=identity
        if (payload["operation"]!="request_entry" or
            (payload["requested_bot"],payload["environment"],
             payload["account"])!=identity or
            OfflineSharedSender._scope(environment,account,
                                      payload["dex"],payload["coin"]) is None):
            return ("hold",False)
        uid=struct.unpack("3i",connection.getsockopt(
            socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize("3i")))[1]
        if type(coordinator) is not OfflineAtomicCoordinator:
            return ("hold",False)
        return coordinator.reserve(
            principal=str(uid)+":"+bot,nonce=payload["nonce"],bot=bot,
            environment=environment,account=account,
            dex=payload["dex"],coin=payload["coin"])
    except Exception:
        return ("hold",False)
