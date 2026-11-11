"""Offline-only Unix socket -> disposable PostgreSQL entry admission tests.

All peers are same-UID synthetic clients; mapping is replaced per test.
This tests payload boundaries, not distinct-UID production isolation.
No Hyperliquid integration, signer, real order, or production database.
"""
import concurrent.futures
import json
import os
import socket
import struct
import unittest

import psycopg

from offline_original_bot_socket_bridge_ci import handle_offline_original_entry_socket

ACCOUNT = "0x" + "1" * 40
BOTS = ("daily", "intraday", "aggressive")


@unittest.skipUnless(
    os.environ.get("ISOLATED_POSTGRES_CI") == "1"
    and os.environ.get("PGDATABASE") == "safety_test"
    and hasattr(socket, "SO_PEERCRED")
    and hasattr(os, "getuid"),
    "Linux and disposable PostgreSQL safety_test only",
)
class OriginalBotSocketBridgeTests(unittest.TestCase):
    @staticmethod
    def admin():
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True,
        )

    @staticmethod
    def factory(bot):
        def connect():
            return psycopg.connect(
                host="localhost", port=5432, dbname="safety_test",
                user="entry_login_" + bot,
                password="disposable-" + bot + "-only",
            )
        return connect

    def setUp(self):
        with self.admin() as db:
            db.execute("truncate public.ci_scoped_entry_intents, "
                       "public.ci_scoped_entry_claims")

    def request(self, *, bot="daily", payload=None, allowed=None,
                factories=None, wire=None):
        request = payload if payload is not None else dict(
            operation="request_entry", action="open_long", side="long",
            hl_coin="SOL", rounded_size="0.025",
        )
        allowed = allowed if allowed is not None else {
            os.getuid(): (bot, "mainnet", ACCOUNT)
        }
        factories = factories if factories is not None else {
            name: self.factory(name) for name in BOTS
        }
        server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            data = (json.dumps(request).encode("utf-8")
                    if wire is None else wire)
            client.sendall(struct.pack("!I", len(data)) + data)
            client.shutdown(socket.SHUT_WR)
            return handle_offline_original_entry_socket(
                server, allowed, factories,
            )
        finally:
            client.close()
            server.close()

    def test_socket_routes_all_three_bot_identities_to_disposable_sql(self):
        for bot, coin, side, action in (
            ("daily", "SOL", "long", "open_long"),
            ("intraday", "AVAX", "short", "open_short"),
            ("aggressive", "LINK", "long", "open_long"),
        ):
            with self.subTest(bot=bot):
                result = self.request(
                    bot=bot,
                    payload=dict(operation="request_entry", action=action,
                                 side=side, hl_coin=coin,
                                 rounded_size="0.025"),
                )
                self.assertEqual(result.state, "reserved_offline_only")
                self.assertFalse(result.submit_authorized)
                with self.admin() as db:
                    row = db.execute(
                        "select bot, action, requested_size, status "
                        "from public.ci_scoped_entry_intents where coin=%s",
                        (coin,),
                    ).fetchone()
                self.assertEqual(row[0:2], (bot, action))
                self.assertEqual(str(row[2]), "0.025")
                self.assertEqual(row[3], "pending")

    def test_concurrent_same_scope_accepts_one_and_holds_rest(self):
        # These are SAME-UID offline socketpairs with independent mappings;
        # true distinct-UID service isolation remains an untested P0 gate.
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(
                lambda bot: self.request(bot=bot), BOTS,
            ))
        self.assertEqual(
            sum(r.state == "reserved_offline_only" for r in results), 1,
            results,
        )
        self.assertEqual(sum(r.state == "hold" for r in results), 2)
        self.assertTrue(all(not r.submit_authorized for r in results))
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_intents"
            ).fetchone()[0], 1)

    def test_unknown_uid_and_spoofed_identity_fields_hold(self):
        self.assertEqual(
            self.request(allowed={}).state, "hold",
        )
        for key, value in (
            ("requested_bot", "intraday"),
            ("account", ACCOUNT),
            ("environment", "testnet"),
            ("dex", ""),
            ("sql", "delete from claims"),
            ("action", "close"),
            ("hl_coin", "SOL/USDC"),
            ("rounded_size", "-1"),
        ):
            with self.subTest(key=key):
                request = dict(operation="request_entry",
                               action="open_long", side="long",
                               hl_coin="SOL", rounded_size="0.025")
                request[key] = value
                self.assertEqual(self.request(payload=request).state, "hold")
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_intents"
            ).fetchone()[0], 0)

    def test_duplicate_json_keys_and_truncated_frame_hold(self):
        duplicate = (b'{"operation":"request_entry",'
                     b'"action":"open_long","side":"long",'
                     b'"hl_coin":"SOL","rounded_size":"0.025",'
                     b'"action":"open_short"}')
        self.assertEqual(self.request(wire=duplicate).state, "hold")
        self.assertEqual(self.request(wire=b"[]").state, "hold")
        self.assertEqual(self.request(wire=b"not-json").state, "hold")
        self.assertEqual(
            self.request(wire=b'{"operation":"request_entry"}').state,
            "hold",
        )
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_intents"
            ).fetchone()[0], 0)

    def test_pinned_bot_database_login_mismatch_holds(self):
        result = self.request(
            bot="daily", factories={"daily": self.factory("intraday")},
        )
        self.assertEqual(result.state, "hold")
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_claims"
            ).fetchone()[0], 0)

    def test_replay_and_other_bot_after_reservation_hold(self):
        first = self.request(bot="daily")
        self.assertEqual(first.state, "reserved_offline_only")
        self.assertEqual(self.request(bot="daily").state, "hold")
        self.assertEqual(self.request(bot="intraday").state, "hold")
        self.assertFalse(first.submit_authorized)
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_intents"
            ).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
