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


    def _simultaneous_attempts(self, coin, *, database_unavailable):
        """Run all three offline entry gates together, with injected DB faults."""
        from shared_entry_gate_staging import inspect_entry

        class FlappingPostgresStore:
            def reserve(self, coin, bot, token):
                if database_unavailable:
                    raise ConnectionError("injected PostgreSQL connection failure")
                with connect() as conn:
                    return conn.execute(
                        "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                        (coin, bot, token, 120)).fetchone()[0]

            def claim_intent(self, coin, bot, token):
                if database_unavailable:
                    raise ConnectionError("injected PostgreSQL connection failure")
                with connect() as conn:
                    return conn.execute(
                        "select public.claim_bot_entry_intent(%s,%s,%s)",
                        (coin, bot, token)).fetchone()[0]

        barrier = threading.Barrier(4)

        def attempt(bot):
            barrier.wait(timeout=10)
            return bot, inspect_entry(
                FlappingPostgresStore(), bot=bot,
                trade={"hl_coin": coin, "action": "open_long"},
                exchange_position_flat=True, exchange_orders_clear=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(attempt, bot) for bot in
                       ("aggressive", "intraday", "daily")]
            barrier.wait(timeout=10)
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_database_flaps_keep_unresolved_intent_fenced(self):
        """Repeated synthetic outages/recovery never bypass a durable fence."""
        coin, owner = "BTC", uuid.uuid4()
        with connect() as conn:
            self.assertTrue(conn.execute(
                "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                (coin, "intraday", owner, 120)).fetchone()[0])
            self.assertTrue(conn.execute(
                "select public.claim_bot_entry_intent(%s,%s,%s)",
                (coin, "intraday", owner)).fetchone()[0])
            # No exchange order ID is available after the exchange times out.
            self.assertTrue(conn.execute(
                "select public.record_bot_entry_order(%s,%s,%s,%s,%s,%s,%s)",
                (coin, "intraday", owner, None, 1793365200000,
                 0.01, "uncertain")).fetchone()[0])
            conn.execute(
                "update public.bot_entry_reservations set expires_at = "
                "now() - interval '1 second' where coin=%s", (coin,))

        for outage in (True, False, True, False):
            with self.subTest(database_unavailable=outage):
                decisions = self._simultaneous_attempts(
                    coin, database_unavailable=outage)
                self.assertEqual(len(decisions), 3)
                for bot, decision in decisions:
                    self.assertFalse(decision.simulated_allowed, bot)
                    self.assertFalse(decision.live_order_submitted, bot)
                with connect() as conn:
                    self.assertEqual(conn.execute(
                        "select bot,token,status,exchange_order_id "
                        "from public.bot_entry_intents where coin=%s",
                        (coin,)).fetchone(),
                        ("intraday", owner, "uncertain", None))

    def test_concurrent_recovery_permits_only_one_new_entry(self):
        """Only a genuinely unclaimed coin may be entered after recovery."""
        coin = "ETH"
        for attempt_number in range(2):
            with self.subTest(outage_round=attempt_number):
                decisions = self._simultaneous_attempts(
                    coin, database_unavailable=True)
                self.assertEqual(len(decisions), 3)
                self.assertTrue(all(
                    not d.simulated_allowed and not d.live_order_submitted
                    for _, d in decisions))
        with connect() as conn:
            self.assertEqual(conn.execute(
                "select count(*) from public.bot_entry_intents "
                "where coin=%s", (coin,)).fetchone()[0], 0)

        decisions = self._simultaneous_attempts(
            coin, database_unavailable=False)
        winners = [bot for bot, result in decisions if result.simulated_allowed]
        self.assertEqual(len(winners), 1, decisions)
        self.assertTrue(all(not result.live_order_submitted
                            for _, result in decisions))
        with connect() as conn:
            self.assertEqual(conn.execute(
                "select bot,status from public.bot_entry_intents "
                "where coin=%s", (coin,)).fetchone(), (winners[0], "pending"))

        # Repeated attempts after recovery cannot override the first winner.
        later = self._simultaneous_attempts(
            coin, database_unavailable=False)
        self.assertTrue(all(not result.simulated_allowed
                            for _, result in later))


if __name__ == "__main__":
    unittest.main()
