"""Fresh-process crash-recovery regression with disposable PostgreSQL only.

Parent writes a durable pending intent and expires its short reservation.
A separate Python interpreter attempts a competing entry, proving that
in-memory lifecycle state is not needed to retain the entry fence.

No exchange, Supabase project, or trading credentials are accessed.
"""
import os
import subprocess
import sys
import unittest
import uuid

from test_entry_reservation_postgres import connect


@unittest.skipUnless(os.environ.get("PGDATABASE") == "safety_test",
                     "Only run against the disposable safety_test database")
class ProcessRestartPostgresTests(unittest.TestCase):
    def setUp(self):
        self.coin = "BTC"
        with connect() as conn:
            conn.execute("truncate public.bot_entry_intents, public.bot_entry_reservations")

    def test_new_interpreter_cannot_claim_expired_reservation_with_intent(self):
        owner = uuid.uuid4()
        with connect() as conn:
            self.assertTrue(conn.execute(
                "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                (self.coin, "intraday", owner, 120)).fetchone()[0])
            self.assertTrue(conn.execute(
                "select public.claim_bot_entry_intent(%s,%s,%s)",
                (self.coin, "intraday", owner)).fetchone()[0])
            conn.execute(
                "update public.bot_entry_reservations set expires_at = "
                "now() - interval '1 second' where coin = %s", (self.coin,))
        child = r'''
import sys, uuid, psycopg
with psycopg.connect() as conn:
    reservation = conn.execute(
        "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
        ("BTC", "aggressive", uuid.uuid4(), 120)).fetchone()[0]
    row = conn.execute(
        "select bot,status from public.bot_entry_intents where coin=%s",
        ("BTC",)).fetchone()
assert reservation is False, "duplicate entry accepted after process restart"
assert row == ("intraday", "pending"), "durable ownership changed"
'''
        result = subprocess.run(
            [sys.executable, "-c", child], env=os.environ.copy(),
            capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        with connect() as conn:
            self.assertEqual(conn.execute(
                "select bot,token,status from public.bot_entry_intents where coin=%s",
                (self.coin,)).fetchone(), ("intraday", owner, "pending"))


    def test_timed_out_order_without_exchange_id_blocks_all_bots_after_restart(self):
        """A timeout with no order ID must remain fenced across new processes."""
        from decimal import Decimal

        owner = uuid.uuid4()
        with connect() as conn:
            self.assertTrue(conn.execute(
                "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                (self.coin, "daily", owner, 120)).fetchone()[0])
            self.assertTrue(conn.execute(
                "select public.claim_bot_entry_intent(%s,%s,%s)",
                (self.coin, "daily", owner)).fetchone()[0])
            # The exchange call timed out: its outcome and order ID are unknown.
            self.assertTrue(conn.execute(
                "select public.record_bot_entry_order(%s,%s,%s,%s,%s,%s,%s)",
                (self.coin, "daily", owner, None, 1793365200000,
                 Decimal("0.01"), "uncertain")).fetchone()[0])
            conn.execute(
                "update public.bot_entry_reservations set expires_at = "
                "now() - interval '1 second' where coin = %s", (self.coin,))

        # Each candidate starts in a new Python interpreter. Even the original
        # owner must not acquire a second reservation until reconciliation.
        child = r"""
import sys
import uuid
import psycopg

bot = sys.argv[1]
with psycopg.connect() as conn:
    accepted = conn.execute(
        "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
        ("BTC", bot, uuid.uuid4(), 120)).fetchone()[0]
    intent = conn.execute(
        "select bot,status,exchange_order_id from public.bot_entry_intents "
        "where coin=%s", ("BTC",)).fetchone()
assert accepted is False, f"{bot}: duplicate entry accepted after restart"
assert intent == ("daily", "uncertain", None), f"{bot}: unknown order fence changed"
"""
        for bot in ("aggressive", "intraday", "daily"):
            with self.subTest(restarted_bot=bot):
                result = subprocess.run(
                    [sys.executable, "-c", child, bot],
                    env=os.environ.copy(), capture_output=True, text=True,
                    timeout=15, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)

        with connect() as conn:
            self.assertEqual(conn.execute(
                "select bot,token,status,exchange_order_id,requested_size "
                "from public.bot_entry_intents where coin=%s",
                (self.coin,)).fetchone(),
                ("daily", owner, "uncertain", None, Decimal("0.01")))


    def test_committed_claim_lost_response_and_database_outage(self):
        """Ambiguous commit + simulated outage must not clear a durable intent."""
        from shared_entry_gate_staging import inspect_entry

        class CommittedClaimTimeoutStore:
            def reserve(self, coin, bot, token):
                with connect() as conn:
                    return conn.execute(
                        "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                        (coin, bot, token, 120)).fetchone()[0]

            def claim_intent(self, coin, bot, token):
                with connect() as conn:
                    committed = conn.execute(
                        "select public.claim_bot_entry_intent(%s,%s,%s)",
                        (coin, bot, token)).fetchone()[0]
                if committed:
                    raise TimeoutError("claim committed but acknowledgement lost")
                return False

        def inspect(store, bot):
            return inspect_entry(
                store, bot=bot,
                trade={"hl_coin": self.coin, "action": "open_long"},
                exchange_position_flat=True, exchange_orders_clear=True)

        # The claim is genuinely committed to disposable PostgreSQL; the bot
        # receives only a timeout and must never mistake it for permission.
        first = inspect(CommittedClaimTimeoutStore(), "intraday")
        self.assertFalse(first.simulated_allowed)
        self.assertFalse(first.live_order_submitted)
        with connect() as conn:
            row = conn.execute(
                "select bot,token,status from public.bot_entry_intents "
                "where coin=%s", (self.coin,)).fetchone()
            self.assertEqual(row[0], "intraday")
            self.assertEqual(row[2], "pending")
            conn.execute(
                "update public.bot_entry_reservations set expires_at = "
                "now() - interval '1 second' where coin=%s", (self.coin,))

        class UnavailableStore:
            def reserve(self, coin, bot, token):
                raise ConnectionError("simulated PostgreSQL outage")

            def claim_intent(self, coin, bot, token):
                raise AssertionError("claim must not run without a reservation")

        for bot in ("aggressive", "intraday", "daily"):
            with self.subTest(bot=bot, stage="database unavailable"):
                denied = inspect(UnavailableStore(), bot)
                self.assertFalse(denied.simulated_allowed)
                self.assertFalse(denied.live_order_submitted)

        # After reconnection, independent new interpreters must consult the
        # persistent fence, not infer that an expired reservation is safe.
        child = r"""
import sys
import psycopg
from shared_entry_gate_staging import inspect_entry

class Store:
    def reserve(self, coin, bot, token):
        with psycopg.connect() as conn:
            return conn.execute(
                "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                (coin, bot, token, 120)).fetchone()[0]

    def claim_intent(self, coin, bot, token):
        with psycopg.connect() as conn:
            return conn.execute(
                "select public.claim_bot_entry_intent(%s,%s,%s)",
                (coin, bot, token)).fetchone()[0]

decision = inspect_entry(
    Store(), bot=sys.argv[1],
    trade={"hl_coin": "BTC", "action": "open_long"},
    exchange_position_flat=True, exchange_orders_clear=True)
assert not decision.simulated_allowed, "entry allowed after DB recovery"
assert not decision.live_order_submitted, "live order submitted"
"""
        for bot in ("aggressive", "intraday", "daily"):
            with self.subTest(bot=bot, stage="fresh process after recovery"):
                result = subprocess.run(
                    [sys.executable, "-c", child, bot],
                    env=os.environ.copy(), capture_output=True, text=True,
                    timeout=15, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)

        with connect() as conn:
            self.assertEqual(conn.execute(
                "select bot,token,status from public.bot_entry_intents "
                "where coin=%s", (self.coin,)).fetchone(), row)



if __name__ == "__main__":
    unittest.main()
