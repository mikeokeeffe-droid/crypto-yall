"""Isolated PostgreSQL tests; no live Supabase or exchange connections."""
import concurrent.futures
import os
import threading
import unittest
import uuid

import psycopg


def connect():
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "safety_test"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "postgres"),
        autocommit=True,
    )


def reserve(coin, bot, token, ttl=120):
    with connect() as conn:
        return conn.execute(
            "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
            (coin, bot, token, ttl),
        ).fetchone()[0]


def release(coin, bot, token):
    with connect() as conn:
        return conn.execute(
            "select public.release_bot_entry(%s,%s,%s)",
            (coin, bot, token),
        ).fetchone()[0]


class EntryReservationPostgresTests(unittest.TestCase):
    def setUp(self):
        with connect() as conn:
            conn.execute("truncate table public.bot_entry_intents, public.bot_entry_reservations")

    def test_concurrent_competing_bots_only_one_wins(self):
        gate = threading.Barrier(3)
        def worker(bot):
            token = uuid.uuid4()
            gate.wait(timeout=10)
            return bot, token, reserve("BTC", bot, token)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(worker, "aggressive")
            b = pool.submit(worker, "intraday")
            gate.wait(timeout=10)
            results = [a.result(timeout=15), b.result(timeout=15)]
        self.assertEqual(sum(int(r[2]) for r in results), 1)
        winner = next(r for r in results if r[2])
        self.assertFalse(release("BTC", "daily", uuid.uuid4()))
        self.assertFalse(release("BTC", winner[0], uuid.uuid4()))
        self.assertTrue(release("BTC", winner[0], winner[1]))

    def test_rollback_does_not_leave_reservation(self):
        token = uuid.uuid4()
        with connect() as conn:
            with conn.transaction() as transaction:
                ok = conn.execute(
                    "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                    ("ETH", "aggressive", token, 120),
                ).fetchone()[0]
                self.assertTrue(ok)
                transaction.force_rollback = True
        self.assertTrue(reserve("ETH", "intraday", uuid.uuid4()))

    def test_unresolved_order_survives_reservation_expiry(self):
        first, second = uuid.uuid4(), uuid.uuid4()
        self.assertTrue(reserve("AVAX", "aggressive", first))
        with connect() as conn:
            self.assertTrue(conn.execute(
                "select public.claim_bot_entry_intent(%s,%s,%s)",
                ("AVAX", "aggressive", first),
            ).fetchone()[0])
            conn.execute(
                "update public.bot_entry_reservations "
                "set expires_at=now()-interval '1 second' where coin='AVAX'"
            )
        self.assertFalse(reserve("AVAX", "intraday", second))
        self.assertFalse(reserve("AVAX", "daily", uuid.uuid4()))
        with connect() as conn:
            self.assertFalse(conn.execute(
                "select public.resolve_bot_entry_intent(%s,%s,%s)",
                ("AVAX", "intraday", second),
            ).fetchone()[0])
            self.assertTrue(conn.execute(
                "select public.resolve_bot_entry_intent(%s,%s,%s)",
                ("AVAX", "aggressive", first),
            ).fetchone()[0])
        self.assertTrue(reserve("AVAX", "intraday", second))

    def test_invalid_arguments_fail_closed(self):
        for coin, bot, ttl in [
            ("BTC", "unknown", 120),
            ("btc!", "aggressive", 120),
            ("BTC", "aggressive", 1),
        ]:
            with self.subTest(coin=coin, bot=bot, ttl=ttl):
                with self.assertRaises(psycopg.Error):
                    reserve(coin, bot, uuid.uuid4(), ttl)

    def test_expired_reservation_can_be_reclaimed(self):
        first, second = uuid.uuid4(), uuid.uuid4()
        self.assertTrue(reserve("SOL", "aggressive", first))
        with connect() as conn:
            conn.execute(
                "update public.bot_entry_reservations "
                "set expires_at=now()-interval '1 second' where coin='SOL'"
            )
        self.assertTrue(reserve("SOL", "intraday", second))
        self.assertFalse(release("SOL", "aggressive", first))
        self.assertTrue(release("SOL", "intraday", second))


if __name__ == "__main__":
    unittest.main()
