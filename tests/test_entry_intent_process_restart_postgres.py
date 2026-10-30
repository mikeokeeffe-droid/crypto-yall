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


if __name__ == "__main__":
    unittest.main()
