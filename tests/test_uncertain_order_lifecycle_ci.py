"""Fail-closed lifecycle regression tests for disposable PostgreSQL only.

No Hyperliquid orders, no production DB, and no automatic reconciler/release.
These checks establish that uncertainty cannot silently clear durable intent.
"""
import os
import subprocess
import sys
import unittest
import uuid

import psycopg
from shared_entry_admission import claim_shared_entry
from restricted_shared_entry_postgres_ci import RestrictedPostgresEntryCoordinator

@unittest.skipUnless(os.getenv("ISOLATED_POSTGRES_CI") == "1" and
                     os.getenv("PGDATABASE") == "safety_test",
                     "disposable safety_test only")
class UncertainOrderLifecycleTests(unittest.TestCase):
    def setUp(self):
        with psycopg.connect(autocommit=True) as db:
            db.execute("truncate public.bot_entry_intents, public.bot_entry_reservations")

    def backend(self, bot):
        def connection():
            return psycopg.connect(
                host="localhost", port=5432, dbname="safety_test",
                user="entry_login_" + bot,
                password="disposable-" + bot + "-only")
        return RestrictedPostgresEntryCoordinator(
            connection, expected_bot=bot,
            expected_login="entry_login_" + bot)

    def enter(self, bot, coin="SOL", action="open_long"):
        return claim_shared_entry(
            self.backend(bot), bot=bot, coin=coin, action=action,
            request_id=str(uuid.uuid4()))

    def test_uncertain_order_and_expired_lease_keep_coin_locked(self):
        first = self.enter("daily")
        self.assertTrue(first.accepted)
        # CI-admin emulates a timeout being recorded by a trusted component.
        # This is not authority to enable unrestricted bot database writes.
        with psycopg.connect(autocommit=True) as db:
            db.execute("update public.bot_entry_intents set status='uncertain' "
                       "where coin='SOL'")
            db.execute("update public.bot_entry_reservations "
                       "set expires_at=now()-interval '1 second' where coin='SOL'")
        self.assertFalse(self.enter("intraday").accepted)
        self.assertFalse(self.enter("aggressive", action="pyramid_long").accepted)
        with psycopg.connect(autocommit=True) as db:
            self.assertEqual(db.execute(
                "select bot,status from public.bot_entry_intents where coin='SOL'"
                ).fetchone(), ("daily", "uncertain"))

    def test_fresh_process_cannot_reclaim_pending_coin(self):
        self.assertTrue(self.enter("aggressive", coin="ETH").accepted)
        child = '''
import psycopg, uuid
with psycopg.connect(host="localhost", port=5432, dbname="safety_test",
                     user="entry_login_intraday",
                     password="disposable-intraday-only") as db:
    assert db.execute(
        "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
        ("ETH", "intraday", uuid.uuid4(), 120)).fetchone()[0] is False
'''
        res = subprocess.run(
            [sys.executable, "-c", child], env=os.environ.copy(),
            capture_output=True, text=True, timeout=15)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_bot_cannot_erase_or_resolve_its_own_unknown_intent(self):
        self.assertTrue(self.enter("daily", coin="BTC").accepted)
        with psycopg.connect(host="localhost", port=5432, dbname="safety_test",
                             user="entry_login_daily",
                             password="disposable-daily-only") as db:
            self.assertFalse(db.execute(
                "select has_function_privilege(current_user,"
                "'public.resolve_bot_entry_intent(text,text,uuid)','EXECUTE')"
                ).fetchone()[0])
            self.assertFalse(db.execute(
                "select has_table_privilege(current_user,"
                "'public.bot_entry_intents','DELETE')"
                ).fetchone()[0])

    def test_db_unavailable_and_untrusted_proof_never_approve(self):
        class Offline:
            def claim_intent(self, **kwargs):
                raise TimeoutError("commit outcome unknown")
        class Forged:
            def claim_intent(self, **kwargs):
                return dict(kwargs, status="claimed",
                            intent_id=str(uuid.uuid4()), fence_token="1")
        for backend in (Offline(), Forged()):
            result = claim_shared_entry(
                backend, bot="daily", coin="LINK",
                action="open_long", request_id=str(uuid.uuid4()))
            self.assertFalse(result.accepted)

if __name__ == "__main__":
    unittest.main()
