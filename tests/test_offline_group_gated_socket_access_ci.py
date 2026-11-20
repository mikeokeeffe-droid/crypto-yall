"""Disposable Linux UID + supplemental-group socket boundary audit.

Root-only CI: a coordinator-owned AF_UNIX socket is group-connectable,
while its SQLite journal and replay ledger are NOT. Linux SO_PEERCRED binds
the three synthetic bots to independent UIDs. The test never imports live
executors, signs, opens AF_INET sockets, or connects to an exchange.

This is NOT a production listener/credential policy: temporary UIDs/GID,
socket and SQLite files are used solely inside a disposable CI directory.
"""
import grp
import json
import os
import pwd
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import unittest

from offline_persistent_replay_ledger import OfflinePersistentReplayLedger
from offline_sender_restart_journal import OfflineRestartJournal
from offline_socket_journal_bridge_fixture import handle_offline_journal_socket

ACCOUNT = "0x" + "1" * 40
BOTS = ("daily", "intraday", "aggressive")

_CHILD_SEND = """
import json,socket,struct,sys
data=json.dumps(json.loads(sys.argv[2]),separators=(',',':')).encode('utf-8')
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
    sock.settimeout(3)
    sock.connect(sys.argv[1])
    sock.sendall(struct.pack('!I',len(data))+data)
print('sent')
"""


def _unused_ids():
    used_uids = {p.pw_uid for p in pwd.getpwall()}
    used_gids = {g.gr_gid for g in grp.getgrall()}
    for p in pwd.getpwall():
        used_gids.add(p.pw_gid)
    values = [n for n in range(51000, 62000) if n not in used_uids]
    gids = [n for n in range(51000, 62000) if n not in used_gids
            and n not in values[:4]]
    if len(values) < 4 or not gids:
        raise AssertionError("disposable unallocated Linux UID/GID unavailable")
    return values[:4], gids[0]


@unittest.skipUnless(
    sys.platform.startswith("linux") and hasattr(os, "geteuid")
    and os.geteuid() == 0 and hasattr(socket, "SO_PEERCRED"),
    "requires root-run disposable Linux CI with SO_PEERCRED",
)
class GroupGatedOriginalBotSocketTests(unittest.TestCase):
    @staticmethod
    def _run_as(uid, groups, code, *args):
        def drop():
            os.setgroups(groups)
            os.setgid(uid)
            os.setuid(uid)
        return subprocess.run(
            [sys.executable, "-c", code, *args],
            preexec_fn=drop,
            env={"PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=8, check=False,
        )

    @staticmethod
    def _payload(bot, coin="SOL"):
        return {
            "operation": "request_entry", "requested_bot": bot,
            "environment": "mainnet", "account": ACCOUNT,
            "dex": "", "coin": coin, "nonce": "group-ci-" + bot + "-" + coin,
        }

    def test_three_distinct_uids_share_only_socket_not_journal(self):
        uids, socket_gid = _unused_ids()
        with tempfile.TemporaryDirectory() as root:
            os.chmod(root, 0o711)
            socket_dir = os.path.join(root, "ipc")
            state_dir = os.path.join(root, "private_state")
            os.mkdir(socket_dir)
            os.chown(socket_dir, 0, socket_gid)
            os.chmod(socket_dir, 0o710)  # group may traverse, NOT enumerate
            os.mkdir(state_dir, 0o700)
            journal = os.path.join(state_dir, "claims.sqlite")
            replay = os.path.join(state_dir, "replay.sqlite")
            OfflineRestartJournal(journal, create=True)
            OfflinePersistentReplayLedger(replay, create=True)
            os.chmod(journal, 0o600)
            os.chmod(replay, 0o600)
            sock_path = os.path.join(socket_dir, "coordinator.sock")
            allowed = {uid: (bot, "mainnet", ACCOUNT)
                       for uid, bot in zip(uids, BOTS)}
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(sock_path)
                os.chown(sock_path, 0, socket_gid)
                os.chmod(sock_path, 0o660)
                server.listen(8)
                server.settimeout(4)
                self.assertEqual(stat.S_IMODE(os.stat(socket_dir).st_mode), 0o710)
                self.assertEqual(stat.S_IMODE(os.stat(sock_path).st_mode), 0o660)
                self.assertEqual(stat.S_IMODE(os.stat(state_dir).st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(os.stat(journal).st_mode), 0o600)
                results = []
                for uid, bot in zip(uids, BOTS):
                    child = self._run_as(
                        uid, [socket_gid], _CHILD_SEND, sock_path,
                        json.dumps(self._payload(bot)),
                    )
                    self.assertEqual(child.returncode, 0, child.stderr)
                    with server.accept()[0] as conn:
                        results.append(handle_offline_journal_socket(
                            conn, allowed, replay, journal))
                self.assertEqual(
                    results.count(("reserved_offline_only", False)), 1, results)
                self.assertEqual(results.count(("hold", False)), 2, results)

                # An unapproved UID without group access cannot connect at all.
                no_group = self._run_as(
                    uids[3], [], _CHILD_SEND, sock_path,
                    json.dumps(self._payload("daily", "AVAX")),
                )
                self.assertNotEqual(no_group.returncode, 0)
                self.assertIn("PermissionError", no_group.stderr)

                # Even an outsider *with* socket-group access fails SO_PEERCRED.
                attacker = self._run_as(
                    uids[3], [socket_gid], _CHILD_SEND, sock_path,
                    json.dumps(self._payload("daily", "AVAX")),
                )
                self.assertEqual(attacker.returncode, 0, attacker.stderr)
                with server.accept()[0] as conn:
                    self.assertEqual(
                        handle_offline_journal_socket(
                            conn, allowed, replay, journal), ("hold", False))

                # Correct UID cannot claim another bot's identity on another coin.
                spoof = self._run_as(
                    uids[0], [socket_gid], _CHILD_SEND, sock_path,
                    json.dumps(self._payload("intraday", "AVAX")),
                )
                self.assertEqual(spoof.returncode, 0, spoof.stderr)
                with server.accept()[0] as conn:
                    self.assertEqual(
                        handle_offline_journal_socket(
                            conn, allowed, replay, journal), ("hold", False))

            # A legitimate socket-group bot still cannot directly open journal.
            read_file = "import sys; open(sys.argv[1], 'rb').read(1)"
            denied = self._run_as(
                uids[0], [socket_gid], read_file, journal,
            )
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("PermissionError", denied.stderr)
            claim = OfflineRestartJournal(journal).inspect(
                environment="mainnet", account=ACCOUNT, dex="", coin="SOL")
            self.assertIsNotNone(claim)
            self.assertIn(claim[0], BOTS)
            self.assertEqual(claim[4], "reserved")
            self.assertIsNone(OfflineRestartJournal(journal).inspect(
                environment="mainnet", account=ACCOUNT, dex="", coin="AVAX"))


if __name__ == "__main__":
    unittest.main()
