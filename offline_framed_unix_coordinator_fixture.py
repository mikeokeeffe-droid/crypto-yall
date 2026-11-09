"""Disposable framed Unix socket request boundary; never submits orders.

Kernel SO_PEERCRED binds UID to a fixed bot scope. A successful identity check
returns identity-only; no journal claim, signer, network, dispatch or close.
"""
import json
import socket
import struct
from offline_unix_peer_identity_fixture import offline_peer_identity

MAX_FRAME=4096

def _read_exact(connection,count):
    chunks=[]
    while count:
        chunk=connection.recv(count)
        if not chunk:
            raise ValueError("truncated frame")
        chunks.append(chunk)
        count-=len(chunk)
    return b"".join(chunks)

def handle_offline_framed_connection(connection,allowed_uids):
    """One bounded request, always fail-closed; no trading authority."""
    try:
        connection.settimeout(1)
        identity=offline_peer_identity(connection,allowed_uids)
        if identity is None:
            return ("hold",False)
        length=struct.unpack("!I",_read_exact(connection,4))[0]
        if length==0 or length>MAX_FRAME:
            return ("hold",False)
        payload=json.loads(_read_exact(connection,length).decode("utf-8"))
        if type(payload) is not dict or set(payload)!={"operation","requested_bot","environment","account"}:
            return ("hold",False)
        if any(type(value) is not str for value in payload.values()):
            return ("hold",False)
        bot,environment,account=identity
        if (payload["operation"]!="request_entry" or
            (payload["requested_bot"],payload["environment"],payload["account"])!=identity):
            return ("hold",False)
        return ("verified_identity_only",False)
    except (OSError,ValueError,UnicodeError,struct.error,TypeError):
        return ("hold",False)
