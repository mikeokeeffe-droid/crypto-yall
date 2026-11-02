"""Isolated CI: test the real PostgreSQL *denial* boundary for reconciliation.

This suite does NOT create a reconciler or grant release permissions.
It deliberately tries forbidden writes with the same three restricted LOGINs
that the trading bots would use, and verifies that the durable intent survives.
No production database, exchange or credentials are involved.
"""
import os
import unittest
import uuid

import psycopg
from psycopg.errors import InsufficientPrivilege

from shared_entry_admission import claim_shared_entry
from restricted_shared_entry_postgres_ci import RestrictedPostgresEntryCoordinator
from entry_reconciliation_review_offline import review_final_no_fill


BOTS = ("daily", "intraday", "aggressive")


@unittest.skipUnless(
    os.getenv("ISOLATED_POSTGRES_CI") == "1"
    and os.getenv("PGDATABASE") == "safety_test",
    "Requires disposable PostgreSQL CI database only",
)
class ReconciliationPermissionBoundaryTests(unittest.TestCase):
    def admin(self):
        return psycopg.connect(
            host=os.environ["PGHOST"], port=int(os.environ["PGPORT"]),
            dbname="safety_test", user="postgres",
            password=os.environ["PGPASSWORD"], autocommit=True,
        )

    def bot_connection(self, bot):
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="entry_login_" + bot,
            password="disposable-" + bot + "-only",
            autocommit=True,
        )

    def setUp(self):
        with self.admin() as db:
            db.execute("truncate public.bot_entry_intents, public.bot_entry_reservations")

    def claim(self, bot, coin):
        backend = RestrictedPostgresEntryCoordinator(
            lambda: self.bot_connection(bot),
            expected_bot=bot, expected_login="entry_login_" + bot,
        )
        result = claim_shared_entry(
            backend, bot=bot, coin=coin, action="open_long",
            request_id=str(uuid.uuid4()),
        )
        self.assertTrue(result.accepted, result.reason)
        return result

    def test_executor_login_cannot_execute_resolve_even_with_own_token(self):
        for bot, coin in zip(BOTS, ("SOL", "BTC", "ETH")):
            with self.subTest(bot=bot):
                self.claim(bot, coin)
                with self.admin() as admin:
                    row = admin.execute(
                        "select token from public.bot_entry_intents where coin=%s",
                        (coin,),
                    ).fetchone()
                with self.bot_connection(bot) as conn:
                    with self.assertRaises(InsufficientPrivilege):
                        conn.execute(
                            "select public.resolve_bot_entry_intent(%s,%s,%s)",
                            (coin, bot, row[0]),
                        )
                    with self.assertRaises(InsufficientPrivilege):
                        conn.execute(
                            "delete from public.bot_entry_intents where coin=%s",
                            (coin,),
                        )
                with self.admin() as admin:
                    self.assertEqual(
                        admin.execute(
                            "select bot,status from public.bot_entry_intents where coin=%s",
                            (coin,),
                        ).fetchone(), (bot, "pending"),
                    )

    def test_bot_logins_cannot_forge_order_evidence_or_ownership(self):
        # Each account must be unable to update even its own claim.
        for bot, coin in zip(BOTS, ("SOL", "BTC", "ETH")):
            with self.subTest(bot=bot):
                claim = self.claim(bot, coin)
                with self.admin() as admin:
                    before = admin.execute(
                        "select bot,token,status,exchange_order_id,"
                        "submitted_at_ms,requested_size,fence_token "
                        "from public.bot_entry_intents where coin=%s",
                        (coin,),
                    ).fetchone()
                with self.bot_connection(bot) as conn:
                    with self.assertRaises(InsufficientPrivilege):
                        conn.execute(
                            "update public.bot_entry_intents "
                            "set exchange_order_id='forged',requested_size=999 "
                            "where coin=%s", (coin,),
                        )
                    with self.assertRaises(InsufficientPrivilege):
                        conn.execute(
                            "select public.record_bot_entry_order("
                            "%s,%s,%s,%s,%s,%s,%s)",
                            (coin, bot, uuid.UUID(claim.intent_id),
                             "forged", 123456, 999, "submitted"),
                        )
                    with self.assertRaises(InsufficientPrivilege):
                        conn.execute(
                            "update public.bot_entry_intents "
                            "set status='filled' where coin=%s", (coin,),
                        )
                with self.admin() as admin:
                    after = admin.execute(
                        "select bot,token,status,exchange_order_id,"
                        "submitted_at_ms,requested_size,fence_token "
                        "from public.bot_entry_intents where coin=%s",
                        (coin,),
                    ).fetchone()
                self.assertEqual(after, before)

    def test_untrusted_roles_have_no_release_privileges(self):
        identities = BOTS + ("bot_entry_executor_trial", "service_role",
                             "anon", "authenticated")
        with self.admin() as db:
            for identity in identities:
                role = identity if identity not in BOTS else "entry_login_" + identity
                with self.subTest(role=role):
                    self.assertFalse(db.execute(
                        "select has_function_privilege(%s,"
                        "'public.resolve_bot_entry_intent(text,text,uuid)','EXECUTE')",
                        (role,),
                    ).fetchone()[0])
                    self.assertFalse(db.execute(
                        "select has_table_privilege(%s,"
                        "'public.bot_entry_intents','DELETE')",
                        (role,),
                    ).fetchone()[0])

    def test_review_candidate_does_not_release_real_database_intent(self):
        self.claim("daily", "LINK")
        # These are SYNTHETIC evidence objects, not authenticated exchange reads.
        order = dict(coin="LINK", order_id="100", status="rejected",
                     final=True, complete=True, filled_size=0)
        first = dict(coin="LINK", fresh=True, complete=True, fills_complete=True,
                     observed_at_ms=2000, position_size=0,
                     open_orders=[], fills=[])
        second = dict(first, observed_at_ms=3000)
        decision = review_final_no_fill(
            coin="LINK", order_id="100", submitted_at_ms=1000,
            order=order, first=first, second=second,
        )
        self.assertEqual(decision.status, "review_candidate")
        # Even if evidence qualifies for review, no untrusted bot may erase it.
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select status from public.bot_entry_intents where coin='LINK'",
            ).fetchone(), ("pending",))

    def test_expired_reservation_does_not_create_release_authority(self):
        self.claim("intraday", "AVAX")
        with self.admin() as db:
            db.execute(
                "update public.bot_entry_reservations "
                "set expires_at=now()-interval '1 second' where coin='AVAX'",
            )
        backend = RestrictedPostgresEntryCoordinator(
            lambda: self.bot_connection("daily"),
            expected_bot="daily", expected_login="entry_login_daily",
        )
        decision = claim_shared_entry(
            backend, bot="daily", coin="AVAX", action="open_long",
            request_id=str(uuid.uuid4()),
        )
        self.assertFalse(decision.accepted)
        with self.admin() as db:
            self.assertEqual(
                db.execute(
                    "select bot,status from public.bot_entry_intents where coin='AVAX'",
                ).fetchone(),
                ("intraday", "pending"),
            )


if __name__ == "__main__":
    unittest.main()
