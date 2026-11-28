"""Root-only disposable CI test with three distinct real Linux UIDs.

The privileged test creates a world-connectable *temporary* Unix socket to
test kernel SO_PEERCRED identity, then removes it. The coordinator owns the
PostgreSQL connections and no bot child receives the connection credentials.
This does not prove a production deployment's credential isolation.
No Hyperliquid SDK, order signer, outbound network or live order calls.
"""
import os
import pwd
import socket
import subprocess
import sys
import tempfile
import unittest
import json
import struct

import psycopg

from offline_original_bot_socket_bridge_ci import (
    handle_offline_original_entry_socket,
)

ACCOUNT = "0x" + "1" * 40
BOTS = ("daily", "intraday", "aggressive")

_CHILD = """
import json, socket, struct, sys
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect(sys.argv[1])
payload = json.loads(sys.argv[2])
data = json.dumps(payload, separators=(',', ':')).encode('utf-8')
sock.sendall(struct.pack('!I', len(data)) + data)
sock.close()
"""


@unittest.skipUnless(
    sys.platform.startswith("linux") and hasattr(os, "geteuid")
    and os.geteuid() == 0 and hasattr(socket, "SO_PEERCRED")
    and os.environ.get("ISOLATED_POSTGRES_CI") == "1"
    and os.environ.get("PGDATABASE") == "safety_test",
    "requires root on disposable Linux safety_test PostgreSQL runner",
)
class DistinctUidOriginalBotPostgresSocketTests(unittest.TestCase):
    @staticmethod
    def _admin():
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True,
        )

    @staticmethod
    def _factory(bot):
        def connect():
            return psycopg.connect(
                host="localhost", port=5432, dbname="safety_test",
                user="entry_login_" + bot,
                password="disposable-" + bot + "-only",
            )
        return connect

    def setUp(self):
        with self._admin() as db:
            db.execute(
                "truncate public.ci_scoped_entry_intents, "
                "public.ci_scoped_entry_claims"
            )

    @staticmethod
    def _nonroot_users():
        selected = []
        seen = set()
        for user in pwd.getpwall():
            if user.pw_uid > 0 and user.pw_uid not in seen:
                selected.append(user)
                seen.add(user.pw_uid)
            if len(selected) == 3:
                return selected
        raise AssertionError("three distinct nonroot Linux UIDs required")

    @staticmethod
    def _send_as(user, path, payload):
        def drop():
            os.setgroups([])
            os.setgid(user.pw_gid)
            os.setuid(user.pw_uid)
        # Do not inherit any test DB credentials or CI secrets into bots.
        child = subprocess.run(
            [sys.executable, "-c", _CHILD, path, json.dumps(payload)],
            preexec_fn=drop, env={"PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=10, check=False,
        )
        return child

    def test_three_real_uids_compete_and_spoofed_scope_is_denied(self):
        users = self._nonroot_users()
        uids = [user.pw_uid for user in users]
        self.assertEqual(len(set(uids)), 3)
        allowed = {
            user.pw_uid: (bot, "mainnet", ACCOUNT)
            for user, bot in zip(users, BOTS)
        }
        factories = {bot: self._factory(bot) for bot in BOTS}
        payload = {
            "operation": "request_entry", "action": "open_long",
            "side": "long", "hl_coin": "SOL", "rounded_size": "0.025",
        }

        with tempfile.TemporaryDirectory() as directory:
            # Execute-only traversal lets unprivileged test clients connect.
            # Deliberately open socket mode is ONLY for this root CI fixture.
            os.chmod(directory, 0o711)
            path = os.path.join(directory, "offline-identity.sock")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(path)
                os.chmod(path, 0o666)
                listener.listen(5)
                listener.settimeout(10)
                for user in users:
                    child = self._send_as(user, path, payload)
                    self.assertEqual(
                        child.returncode, 0, child.stdout + child.stderr,
                    )
                results = []
                for _ in users:
                    with listener.accept()[0] as conn:
                        results.append(handle_offline_original_entry_socket(
                            conn, allowed, factories,
                        ))
                self.assertEqual(
                    sum(item.state == "reserved_offline_only"
                        for item in results), 1, results,
                )
                self.assertEqual(
                    sum(item.state == "hold" for item in results), 2,
                )
                self.assertTrue(all(
                    not item.submit_authorized for item in results
                ))
                with self._admin() as db:
                    original = db.execute(
                        "select c.bot,c.token,i.bot,i.intent_token,i.status "
                        "from public.ci_scoped_entry_claims c "
                        "join public.ci_scoped_entry_intents i "
                        "on i.intent_token=c.token"
                    ).fetchall()
                self.assertEqual(len(original), 1)
                self.assertEqual(original[0][0], original[0][2])
                self.assertEqual(original[0][1], original[0][3])
                self.assertEqual(original[0][4], "pending")

                invalid_requests = (
                    (users[0], dict(payload, requested_bot="intraday")),
                    (users[1], dict(payload, account="0x" + "2" * 40)),
                )
                for user, request in invalid_requests:
                    child = self._send_as(user, path, request)
                    self.assertEqual(
                        child.returncode, 0, child.stdout + child.stderr,
                    )
                for _ in invalid_requests:
                    with listener.accept()[0] as conn:
                        rejected = handle_offline_original_entry_socket(
                            conn, allowed, factories,
                        )
                        self.assertEqual(rejected.state, "hold")
                        self.assertFalse(rejected.submit_authorized)
            with self._admin() as db:
                self.assertEqual(db.execute(
                    "select c.bot,c.token,i.bot,i.intent_token,i.status "
                    "from public.ci_scoped_entry_claims c "
                    "join public.ci_scoped_entry_intents i "
                    "on i.intent_token=c.token"
                ).fetchall(), original)


if __name__ == "__main__":
    unittest.main()
