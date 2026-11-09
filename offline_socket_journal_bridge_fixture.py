"""Offline socket-to-journal bridge; no live execution authority.

Kernel UID binds identity; nonce consumed durably before a disposable claim.
Two SQLite files are NOT one atomic transaction: a crash between writes can
burn a nonce without a claim (safe HOLD), and no trading is authorized.
"""
import json
import socket
import struct
from offline_unix_peer_identity_fixture import offline_peer_identity
from offline_framed_unix_coordinator_fixture import MAX_FRAME,_read_exact
from offline_persistent_replay_ledger import OfflinePersistentReplayLedger
from offline_sender_restart_journal import OfflineRestartJournal

def handle_offline_journal_socket(connection,allowed_uids,replay_path,journal_path):
    try:
        connection.settimeout(1)
        identity=offline_peer_identity(connection,allowed_uids)
        if identity is None:
            return ("hold",False)
        size=struct.unpack("!I",_read_exact(connection,4))[0]
        if not 0<size<=MAX_FRAME:
            return ("hold",False)
        payload=json.loads(_read_exact(connection,size).decode("utf-8"))
        required={"operation","requested_bot","environment","account","dex","coin","nonce"}
        if type(payload) is not dict or set(payload)!=required:
            return ("hold",False)
        if any(type(value) is not str for value in payload.values()):
            return ("hold",False)
        bot,environment,account=identity
        if (payload["operation"]!="request_entry" or
            (payload["requested_bot"],payload["environment"],payload["account"])!=identity or
            not 1<=len(payload["nonce"])<=128):
            return ("hold",False)
        # Validate the journal before consuming a nonce. Never recreate missing files.
        journal=OfflineRestartJournal(journal_path)
        ledger=OfflinePersistentReplayLedger(replay_path)
        if not ledger.consume(str(struct.unpack("3i",connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1])+":"+bot,
                              payload["nonce"]):
            return ("hold",False)
        reserved=journal.reserve(bot=bot,environment=environment,account=account,
                                 dex=payload["dex"],coin=payload["coin"])
        return ("reserved_offline_only",False) if reserved else ("hold",False)
    except Exception:
        return ("hold",False)
