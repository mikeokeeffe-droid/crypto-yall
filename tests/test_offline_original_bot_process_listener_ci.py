"""A real *separate process* offline Unix listener backed by disposable SQL.

Same-UID child processes prove restart and connection behaviour, not
production principal isolation. There are no exchange APIs or trade secrets.
"""
import json
import multiprocessing
import os
import socket
import struct
import tempfile
import unittest
import uuid

import psycopg

from offline_original_bot_process_listener_ci import (
    serve_offline_original_entry_requests,
)
from offline_original_bot_entry_socket_client_ci import request_offline_entry_via_unix_socket

ACCOUNT = "0x" + "1" * 40


def _read_exact(peer, size):
    parts = []
    while size:
        block = peer.recv(size)
        if not block:
            raise EOFError("truncated response")
        parts.append(block)
        size -= len(block)
    return b"".join(parts)


def _serve_one(socket_path, ready):
    def database_connection():
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="entry_login_daily", password="disposable-daily-only",
        )

    serve_offline_original_entry_requests(
        socket_path=socket_path,
        allowed_uids={os.getuid(): ("daily", "mainnet", ACCOUNT)},
        connection_factories={"daily": database_connection},
        max_requests=1,
        ready=ready,
    )


@unittest.skipUnless(
    os.environ.get("ISOLATED_POSTGRES_CI") == "1"
    and os.environ.get("PGDATABASE") == "safety_test"
    and hasattr(socket, "SO_PEERCRED")
    and hasattr(os, "getuid"),
    "requires disposable PostgreSQL and Linux Unix peer credentials",
)
class OriginalBotProcessListenerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "offline-controller.sock")
        self.ctx = multiprocessing.get_context("fork")
        with psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True,
        ) as db:
            db.execute(
                "truncate public.ci_scoped_entry_intents, "
                "public.ci_scoped_entry_claims"
            )

    def _start(self):
        ready = self.ctx.Event()
        process = self.ctx.Process(
            target=_serve_one, args=(self.path, ready),
        )
        process.start()
        self.addCleanup(self._stop_if_alive, process)
        self.assertTrue(ready.wait(timeout=8), "offline process not ready")
        return process

    @staticmethod
    def _stop_if_alive(process):
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)

    def _request(self, *, payload=None, lost_ack=False):
        if payload is None:
            payload = dict(
                operation="request_entry", action="open_long", side="long",
                hl_coin="SOL", rounded_size="0.025",
            )
        data = json.dumps(payload).encode("utf-8")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(4)
            client.connect(self.path)
            client.sendall(struct.pack("!I", len(data)) + data)
            client.shutdown(socket.SHUT_WR)
            if lost_ack:
                return None
            length = struct.unpack("!I", _read_exact(client, 4))[0]
            self.assertLessEqual(length, 1024)
            return json.loads(_read_exact(client, length).decode("utf-8"))

    def _finish(self, process):
        process.join(timeout=8)
        self.assertFalse(process.is_alive(), "offline coordinator hung")
        self.assertEqual(process.exitcode, 0)
        self.assertFalse(os.path.lexists(self.path))

    def _saved(self):
        with psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True,
        ) as db:
            return db.execute(
                "select c.bot,c.token,i.intent_token,i.action,"
                "i.requested_size,i.status "
                "from public.ci_scoped_entry_claims c "
                "join public.ci_scoped_entry_intents i "
                "on i.intent_token=c.token"
            ).fetchall()

    def test_signer_free_client_reaches_separate_ci_process_without_order_rights(self):
        if os.getuid() <= 0:
            self.skipTest("client test requires nonroot CI runner user")
        process=self._start()
        reviewed=request_offline_entry_via_unix_socket(
            socket_path=self.path, expected_coordinator_uid=os.getuid(),
            verified_bot="daily",
            trade={"action":"open_long","side":"long","hl_coin":"SOL"},
            rounded_size="0.025", pinned_environment="mainnet",
            pinned_account=ACCOUNT,
        )
        self._finish(process)
        self.assertEqual(reviewed.state,"recorded_offline_only")
        self.assertFalse(reviewed.submit_authorized)
        rows=self._saved()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][0],"daily")
        self.assertEqual(rows[0][3],"open_long")
        self.assertEqual(str(rows[0][4]),"0.025")

    def test_signer_free_client_rejects_bad_actions_and_server_identity(self):
        if os.getuid() <= 0:
            self.skipTest("client test requires nonroot CI runner user")
        process=self._start()
        bad=request_offline_entry_via_unix_socket(
            socket_path=self.path, expected_coordinator_uid=os.getuid(),
            verified_bot="daily",
            trade={"action":"close","side":"long","hl_coin":"SOL"},
            rounded_size="0.025", pinned_environment="mainnet",
            pinned_account=ACCOUNT,
        )
        mismatch=request_offline_entry_via_unix_socket(
            socket_path=self.path, expected_coordinator_uid=os.getuid()+1000,
            verified_bot="daily",
            trade={"action":"open_long","side":"long","hl_coin":"SOL"},
            rounded_size="0.025", pinned_environment="mainnet",
            pinned_account=ACCOUNT,
        )
        self.assertEqual(bad.state,"hold")
        self.assertEqual(mismatch.state,"hold")
        self.assertFalse(bad.submit_authorized)
        self.assertFalse(mismatch.submit_authorized)
        # Neither invalid request consumed the one-shot coordinator.
        good=request_offline_entry_via_unix_socket(
            socket_path=self.path, expected_coordinator_uid=os.getuid(),
            verified_bot="daily",
            trade={"action":"open_long","side":"long","hl_coin":"SOL"},
            rounded_size="0.025", pinned_environment="mainnet",
            pinned_account=ACCOUNT,
        )
        self._finish(process)
        self.assertEqual(good.state,"recorded_offline_only")
        self.assertFalse(good.submit_authorized)
        self.assertEqual(len(self._saved()),1)

    def test_separate_process_reserves_then_restart_holds(self):
        first = self._start()
        reply = self._request()
        self._finish(first)
        self.assertEqual(
            reply, {"state": "reserved_offline_only",
                    "submit_authorized": False},
        )
        rows = self._saved()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "daily")
        self.assertEqual(rows[0][1], rows[0][2])
        self.assertEqual(rows[0][3], "open_long")
        self.assertEqual(str(rows[0][4]), "0.025")
        self.assertEqual(rows[0][5], "pending")
        second = self._start()
        retry = self._request()
        self._finish(second)
        self.assertEqual(
            retry, {"state": "hold", "submit_authorized": False},
        )
        self.assertEqual(self._saved(), rows)

    def test_lost_reply_after_committed_reservation_never_reopens(self):
        first = self._start()
        self._request(lost_ack=True)
        self._finish(first)
        rows = self._saved()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], rows[0][2])
        second = self._start()
        reply = self._request()
        self._finish(second)
        self.assertEqual(reply["state"], "hold")
        self.assertFalse(reply["submit_authorized"])
        self.assertEqual(self._saved(), rows)

    def test_spoofed_account_payload_does_not_create_reservation(self):
        first = self._start()
        reply = self._request(payload=dict(
            operation="request_entry", action="open_long", side="long",
            hl_coin="SOL", rounded_size="0.025",
            account="0x" + "2" * 40,
        ))
        self._finish(first)
        self.assertEqual(reply["state"], "hold")
        self.assertFalse(reply["submit_authorized"])
        self.assertEqual(self._saved(), [])
        second = self._start()
        good = self._request()
        self._finish(second)
        self.assertEqual(good["state"], "reserved_offline_only")
        self.assertFalse(good["submit_authorized"])
        self.assertEqual(len(self._saved()), 1)


if __name__ == "__main__":
    unittest.main()
