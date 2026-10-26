"""Isolated PostgreSQL three-bot collision and restart safety acceptance.

Uses real transactional reservation/intent RPCs against disposable CI database.
No exchange connections, no trading orders, no production credentials.
"""
import concurrent.futures
import threading
import unittest
import uuid

from test_entry_reservation_postgres import connect


class ThreeBotPostgresAcceptance(unittest.TestCase):
    def setUp(self):
        with connect() as conn:
            conn.execute("truncate table public.bot_entry_intents, public.bot_entry_reservations")

    def test_three_bots_compete_only_one_reservation_and_claim(self):
        barrier = threading.Barrier(4)
        def attempt(bot):
            token = uuid.uuid4()
            barrier.wait(timeout=10)
            with connect() as conn:
                reserved = conn.execute(
                    "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                    ("BTC", bot, token, 120)).fetchone()[0]
                claimed = False
                if reserved:
                    claimed = conn.execute(
                        "select public.claim_bot_entry_intent(%s,%s,%s)",
                        ("BTC", bot, token)).fetchone()[0]
                return bot, token, reserved, claimed
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [pool.submit(attempt, bot) for bot in
                    ("aggressive", "intraday", "daily")]
            barrier.wait(timeout=10)
            outcomes = [job.result(timeout=20) for job in jobs]
        self.assertEqual(sum(int(x[2]) for x in outcomes), 1)
        self.assertEqual(sum(int(x[3]) for x in outcomes), 1)
        winner = next(x for x in outcomes if x[3])
        with connect() as conn:
            intent = conn.execute(
                "select bot, token, status from public.bot_entry_intents "
                "where coin='BTC'").fetchone()
        self.assertEqual(intent, (winner[0], winner[1], "pending"))

    def test_restart_and_expired_reservation_never_override_durable_intent(self):
        owner = uuid.uuid4()
        with connect() as conn:
            self.assertTrue(conn.execute(
                "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                ("ETH", "daily", owner, 120)).fetchone()[0])
            self.assertTrue(conn.execute(
                "select public.claim_bot_entry_intent(%s,%s,%s)",
                ("ETH", "daily", owner)).fetchone()[0])
            conn.execute("update public.bot_entry_reservations "
                         "set expires_at=now()-interval '1 second' where coin='ETH'")
        for bot in ("aggressive", "intraday", "daily"):
            with self.subTest(bot=bot), connect() as restarted:
                self.assertFalse(restarted.execute(
                    "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                    ("ETH", bot, uuid.uuid4(), 120)).fetchone()[0])
        with connect() as conn:
            self.assertEqual(conn.execute(
                "select bot, token from public.bot_entry_intents "
                "where coin='ETH'").fetchone(), ("daily", owner))


if __name__ == "__main__":
    unittest.main()
