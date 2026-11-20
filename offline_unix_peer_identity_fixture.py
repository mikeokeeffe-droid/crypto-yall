"""Linux-only offline Unix socket peer-credential fixture.

Uses kernel SO_PEERCRED, not caller-supplied identity. No journal, SDK,
network service, signer or live order capability. A real coordinator still
needs isolated service identities and an authenticated request protocol.
"""
import socket
import struct

def offline_peer_identity(connection,allowed_uids):
    if not hasattr(socket,"SO_PEERCRED"):
        return None
    try:
        raw=connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,
                                  struct.calcsize("3i"))
        pid,uid,gid=struct.unpack("3i",raw)
    except (OSError,ValueError,struct.error):
        return None
    identity=allowed_uids.get(uid)
    if (type(uid) is not int or type(pid) is not int or pid<=0
            or type(identity) is not tuple or len(identity)!=3):
        return None
    return identity

def offline_socket_request(connection,allowed_uids,claimed_bot):
    identity=offline_peer_identity(connection,allowed_uids)
    if identity is None or type(claimed_bot) is not str or identity[0]!=claimed_bot:
        return ("hold",False)
    return ("verified_identity_only",False)
