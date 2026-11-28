"""PostgreSQL integration against CI's disposable safety_test DB only.

This checks the existing RPCs across separate transactions/processes, without
connecting to Supabase, Hyperliquid, live credentials, or paid infrastructure.
The SQL remains staging-only and does NOT authorize live order submission.
"""
import concurrent.futures
import os
import subprocess
import sys
import unittest
import uuid

import psycopg


@unittest.skipUnless(os.getenv("PGDATABASE") == "safety_test" and
                     os.getenv("ISOLATED_POSTGRES_CI") == "1",
                     "Requires the isolated disposable PostgreSQL CI service")
class SharedEntryPostgresIntegrationTests(unittest.TestCase):
    def connect(self):
        return psycopg.connect(autocommit=True)

    def setUp(self):
        with self.connect() as db:
            db.execute("truncate public.bot_entry_intents, public.bot_entry_reservations")

    def claim(self, coin, bot):
        token = uuid.uuid4()
        with self.connect() as db:
            # One DB transaction: reserve + durable intent commit together.
            with db.transaction():
                reserved = db.execute(
                    "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                    (coin, bot, token, 120)).fetchone()[0]
                if not reserved:
                    return False
                intent = db.execute(
                    "select public.claim_bot_entry_intent(%s,%s,%s)",
                    (coin, bot, token)).fetchone()[0]
                if not intent:
                    raise RuntimeError("reserved without durable intent")
            return True

    def test_three_bots_compete_one_durable_coin_intent(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(self.claim, "SOL", bot)
                       for bot in ("daily", "intraday", "aggressive")]
            outcomes = [f.result(timeout=15) for f in futures]
        self.assertEqual(outcomes.count(True), 1)
        with self.connect() as db:
            row = db.execute(
                "select coin,bot,status from public.bot_entry_intents"
                ).fetchall()
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0][0], "SOL")
        self.assertEqual(row[0][2], "pending")

    def test_expired_reservation_with_intent_still_blocks(self):
        self.assertTrue(self.claim("BTC", "aggressive"))
        with self.connect() as db:
            db.execute("update public.bot_entry_reservations "
                       "set expires_at=now()-interval '1 second' where coin='BTC'")
        self.assertFalse(self.claim("BTC", "intraday"))
        self.assertFalse(self.claim("BTC", "daily"))

    def test_fresh_process_cannot_take_pending_coin(self):
        self.assertTrue(self.claim("ETH", "daily"))
        child = """
import psycopg, uuid
with psycopg.connect(autocommit=True) as db:
    assert db.execute(
        'select public.try_reserve_bot_entry(%s,%s,%s,%s)',
        ('ETH', 'intraday', uuid.uuid4(), 120)).fetchone()[0] is False
"""
        res = subprocess.run([sys.executable, "-c", child],
                             capture_output=True, text=True,
                             env=os.environ.copy(), timeout=15)
        self.assertEqual(res.returncode, 0, res.stderr)


if __name__ == "__main__":
    unittest.main()
