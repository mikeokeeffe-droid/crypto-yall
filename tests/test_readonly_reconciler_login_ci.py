"""Disposable PostgreSQL-only read-only reconciler identity test.

This role is created inside an ephemeral GitHub Actions database. It is NOT a
production reconciler, does not authenticate Hyperliquid evidence, and cannot
unlock or transfer any ownership. No existing role grants are modified.
"""
import os
import unittest
import uuid

import psycopg
from psycopg.errors import InsufficientPrivilege

from restricted_shared_entry_postgres_ci import RestrictedPostgresEntryCoordinator
from shared_entry_admission import claim_shared_entry

REVIEW_LOGIN = "ci_reconciliation_reader"
REVIEW_PASSWORD = "disposable-reconciliation-reader-only"


@unittest.skipUnless(
    os.environ.get("ISOLATED_POSTGRES_CI") == "1"
    and os.environ.get("PGDATABASE") == "safety_test",
    "Disposable GitHub Actions safety_test PostgreSQL only",
)
class ReadOnlyReconcilerLoginTests(unittest.TestCase):
    @classmethod
    def admin(cls):
        return psycopg.connect(
            host=os.environ["PGHOST"], port=int(os.environ["PGPORT"]),
            dbname="safety_test", user="postgres",
            password=os.environ["PGPASSWORD"], autocommit=True,
        )

    @classmethod
    def setUpClass(cls):
        with cls.admin() as db:
            db.execute(
                "create role ci_reconciliation_reader "
                "login noinherit password 'disposable-reconciliation-reader-only'"
            )
            db.execute("grant usage on schema public to ci_reconciliation_reader")
            db.execute(
                "grant select (coin,bot,token,status,exchange_order_id,"
                "submitted_at_ms,requested_size,fence_token) "
                "on public.bot_entry_intents to ci_reconciliation_reader"
            )

    @classmethod
    def tearDownClass(cls):
        with cls.admin() as db:
            db.execute("drop owned by ci_reconciliation_reader")
            db.execute("drop role ci_reconciliation_reader")

    def reviewer(self):
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user=REVIEW_LOGIN, password=REVIEW_PASSWORD, autocommit=True,
        )

    def bot(self):
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="entry_login_daily", password="disposable-daily-only",
        )

    def setUp(self):
        with self.admin() as db:
            db.execute("truncate public.bot_entry_intents, public.bot_entry_reservations")
        backend = RestrictedPostgresEntryCoordinator(
            self.bot, expected_bot="daily", expected_login="entry_login_daily"
        )
        self.claim = claim_shared_entry(
            backend, bot="daily", coin="SOL", action="open_long",
            request_id=str(uuid.uuid4()),
        )
        self.assertTrue(self.claim.accepted, self.claim.reason)

    def test_separate_login_can_read_only_durable_claim_columns(self):
        with self.reviewer() as db:
            self.assertEqual(
                db.execute("select session_user,current_user").fetchone(),
                (REVIEW_LOGIN, REVIEW_LOGIN),
            )
            record = db.execute(
                "select coin,bot,token,status,exchange_order_id,"
                "submitted_at_ms,requested_size,fence_token "
                "from public.bot_entry_intents where coin='SOL'"
            ).fetchone()
            self.assertEqual(record[:4], (
                "SOL", "daily", uuid.UUID(self.claim.intent_id), "pending"
            ))
            self.assertEqual(record[4:7], (None, None, None))
            self.assertEqual(record[7], self.claim.fence_token)
            with self.assertRaises(InsufficientPrivilege):
                db.execute("select updated_at from public.bot_entry_intents")
            with self.assertRaises(InsufficientPrivilege):
                db.execute("select * from public.bot_entry_executor_identities")

    def test_reader_cannot_modify_or_release_an_intent(self):
        with self.reviewer() as db:
            with self.assertRaises(InsufficientPrivilege):
                db.execute(
                    "update public.bot_entry_intents set status='filled' "
                    "where coin='SOL'"
                )
            with self.assertRaises(InsufficientPrivilege):
                db.execute(
                    "delete from public.bot_entry_intents where coin='SOL'"
                )
            with self.assertRaises(InsufficientPrivilege):
                db.execute(
                    "insert into public.bot_entry_intents(coin,bot,token,status) "
                    "values('BTC','daily',%s,'pending')", (uuid.uuid4(),),
                )
            with self.assertRaises(InsufficientPrivilege):
                db.execute(
                    "select public.resolve_bot_entry_intent(%s,%s,%s)",
                    ("SOL", "daily", uuid.UUID(self.claim.intent_id)),
                )
            with self.assertRaises(InsufficientPrivilege):
                db.execute(
                    "select public.record_bot_entry_order(%s,%s,%s,%s,%s,%s,%s)",
                    ("SOL", "daily", uuid.UUID(self.claim.intent_id),
                     "forged", 1000, 999, "submitted"),
                )
            with self.assertRaises(InsufficientPrivilege):
                db.execute(
                    "select public.release_bot_entry(%s,%s,%s)",
                    ("SOL", "daily", uuid.UUID(self.claim.intent_id)),
                )
        with self.admin() as db:
            self.assertEqual(
                db.execute(
                    "select status from public.bot_entry_intents "
                    "where coin='SOL'"
                ).fetchone(),
                ("pending",),
            )

    def test_reviewer_has_no_claim_or_unlock_rpc_permissions(self):
        # Query effective grants; no writes, exchange API, or order actions.
        rpc_signatures = (
            "public.try_reserve_bot_entry(text,text,uuid,integer)",
            "public.claim_bot_entry_intent(text,text,uuid)",
            "public.record_bot_entry_order(text,text,uuid,text,bigint,numeric,text)",
            "public.release_bot_entry(text,text,uuid)",
            "public.resolve_bot_entry_intent(text,text,uuid)",
        )
        with self.reviewer() as db:
            for signature in rpc_signatures:
                with self.subTest(function=signature):
                    self.assertFalse(db.execute(
                        "select has_function_privilege(current_user,%s,'EXECUTE')",
                        (signature,),
                    ).fetchone()[0])
            for target in ("public.bot_entry_intents",
                           "public.bot_entry_reservations",
                           "public.bot_entry_executor_identities"):
                with self.subTest(table=target):
                    for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                        self.assertFalse(db.execute(
                            "select has_table_privilege(current_user,%s,%s)",
                            (target, privilege),
                        ).fetchone()[0])

    def test_separate_identity_cannot_impersonate_executor_or_admin(self):
        with self.reviewer() as db:
            for role in ("entry_login_daily", "postgres", "bot_entry_executor_trial"):
                with self.subTest(role=role):
                    with self.assertRaises(InsufficientPrivilege):
                        db.execute("set role " + role)
            self.assertEqual(
                db.execute("select session_user,current_user").fetchone(),
                (REVIEW_LOGIN, REVIEW_LOGIN),
            )
        with self.bot() as db:
            with self.assertRaises(InsufficientPrivilege):
                db.execute("set role " + REVIEW_LOGIN)


if __name__ == "__main__":
    unittest.main()
