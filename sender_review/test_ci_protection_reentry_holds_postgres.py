"""Disposable PostgreSQL-only proof of persistent synthetic protective locks.

No network, real orders, signer, real protected exit, production roles, or
deployed workflow. This is NOT proof of live safety. SQL's only path is an
append-only HOLD with no release. Only the disposable local CI database is
permitted. Separate connections, crashes and cross-bot claims are tested.
"""
import concurrent.futures
import os
from pathlib import Path
import unittest

import psycopg

from sender_review.ci_only_identity_bridge import (
    inspect_and_record_signed_fixture_offline,
)
from sender_review.test_ci_journal_postgres import (
    ACCOUNT, CI_MARKER, SQL, connect,
)
from sender_review.test_offline_oidc_identity_fixture import (
    NOW, POLICY, SignedOidcFixtureTests,
)

SCRIPT = Path(__file__).with_name("ci_only_protection_reentry_holds.sql")
TABLE = "sender_review_ci.simulated_protection_reentry_holds"
FUNC = "sender_review_ci.record_ci_protection_reentry_hold"
VIEW = "sender_review_ci.simulated_protection_hold_review"


@unittest.skipUnless(
    os.environ.get(CI_MARKER) == "1"
    and os.environ.get("PGDATABASE") == "sender_review_test"
    and os.environ.get("PGHOST") == "127.0.0.1",
    "Disposable localhost PostgreSQL CI only",
)
class ProtectionHoldPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SignedOidcFixtureTests.setUpClass()
        cls.fixture = SignedOidcFixtureTests()
        cls.keys = SignedOidcFixtureTests.keys
        with connect() as conn:
            conn.execute(SQL.read_text("utf-8"))
            conn.execute(SCRIPT.read_text("utf-8"))

    def setUp(self):
        with connect() as conn:
            conn.execute(
                "TRUNCATE sender_review_ci.fixture_identity_receipts,"
                "sender_review_ci.review_events,"
                "sender_review_ci.review_intents,"
                "sender_review_ci.scope_fences RESTART IDENTITY CASCADE"
            )

    def query(self, sql, args=()):
        with connect() as db:
            return db.execute(sql, args).fetchall()

    def seed_signed_fixture(self, bot="daily", coin="SOL", nonce="a"*32):
        body = (
            b'{"version":1,"action":"open_long","side":"long",'
            b'"coin":"' + coin.encode("ascii") +
            b'","rounded_size":"0.16","requested_leverage":2,'
            b'"request_nonce":"' + nonce.encode("ascii") + b'"}'
        )
        result = inspect_and_record_signed_fixture_offline(
            token=self.fixture.token(bot, jti="protection-" + bot + "-" + coin),
            body=body, policy=POLICY, fixture_keys=self.keys,
            fixture_now_seconds=NOW, fixed_test_account=ACCOUNT,
            db_password=os.environ["PGPASSWORD"],
        )
        self.assertTrue(result.journal_recorded)
        self.assertFalse(result.submit_authorized)
        return result.assigned_fence

    @staticmethod
    def record(bot="daily", coin="SOL", side="long", nonce="a"*32,
               fence=1, outcome="unknown_ack", account=ACCOUNT):
        with connect() as db:
            return db.execute(
                "SELECT recorded,reason FROM " + FUNC +
                "(%s,%s,%s,%s,%s,%s,%s)",
                (account, bot, coin, side, nonce, fence, outcome),
            ).fetchone()

    def test_no_unsigned_entry_fixture_or_wrong_fence_can_record_hold(self):
        self.assertEqual(self.record(), (False, "unverified-or-unheld-fixture"))
        self.seed_signed_fixture()
        for changes in (
            dict(bot="aggressive"), dict(coin="AVAX"),
            dict(side="short"), dict(nonce="b"*32),
            dict(fence=2), dict(account="0x"+"2"*40),
            dict(outcome="filled"), dict(fence=True),
        ):
            with self.subTest(changes=changes):
                self.assertFalse(self.record(**changes)[0])
        self.assertEqual(self.query("SELECT count(*) FROM " + TABLE), [(0,)])

    def test_permanent_hold_and_claimed_closed_never_release(self):
        self.seed_signed_fixture()
        self.assertEqual(self.record(outcome="claimed_closed"), (
            True, "durable-review-only-protection-HOLD"
        ))
        self.assertEqual(self.record(outcome="unknown_ack"), (
            False, "existing-protection-hold-retained"
        ))
        self.assertEqual(self.query(
            "SELECT bot,coin,side,outcome_fixture FROM " + TABLE
        ), [("daily", "SOL", "long", "claimed_closed")])
        self.assertEqual(self.query(
            "SELECT fence_still_held,review_state FROM " + VIEW
        ), [(True, "PERMANENT_REVIEW_ONLY_HOLD")])
        from sender_review.test_ci_journal_postgres import record
        denied = record(bot="aggressive", coin="SOL", nonce="b"*32)
        self.assertFalse(denied[0])
        self.assertEqual(denied[2], "active-scope-held")

    def test_fresh_connection_sees_same_hold_and_source_id(self):
        self.seed_signed_fixture()
        self.assertTrue(self.record()[0])
        with connect() as observer:
            result = observer.execute(
                "SELECT h.source_intent_id,h.fence,h.request_nonce,"
                "i.bot,i.state,s.active_nonce FROM " + TABLE +
                " h JOIN sender_review_ci.review_intents i "
                "ON i.id=h.source_intent_id JOIN sender_review_ci.scope_fences s "
                "ON s.environment=h.environment AND s.account=h.account "
                "AND s.dex=h.dex AND s.coin=h.coin"
            ).fetchone()
        self.assertEqual(result, (1, 1, "a"*32, "daily", "review_only", "a"*32))
        self.assertFalse(self.record(bot="intraday")[0])

    def test_concurrent_duplicate_holds_only_one_wins(self):
        self.seed_signed_fixture()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: self.record(), range(3)))
        self.assertEqual(sum(bool(r[0]) for r in results), 1)
        self.assertEqual(self.query("SELECT count(*) FROM " + TABLE), [(1,)])

    def test_missing_fence_is_critical_and_immutable_row_cannot_be_edited(self):
        self.seed_signed_fixture()
        self.assertTrue(self.record()[0])
        for stmt in (
            "UPDATE " + TABLE + " SET outcome_fixture='claimed_closed'",
            "DELETE FROM " + TABLE,
        ):
            with self.subTest(stmt=stmt):
                with connect() as db:
                    with self.assertRaises(psycopg.errors.RaiseException):
                        db.execute(stmt)
        with connect() as db:
            db.execute(
                "UPDATE sender_review_ci.scope_fences SET active_nonce=NULL"
                " WHERE coin='SOL'"
            )
        self.assertEqual(self.query(
            "SELECT fence_still_held,review_state FROM " + VIEW
        ), [(False, "CRITICAL_FENCE_MISSING_OR_CHANGED")])
        self.assertFalse(self.record()[0])

    def test_no_untrusted_role_granted_access_or_release(self):
        self.seed_signed_fixture()
        self.assertTrue(self.record()[0])
        role = "sender_review_protection_untrusted"
        with connect() as db:
            db.execute("CREATE ROLE "+role+" NOLOGIN NOSUPERUSER "
                       "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
        try:
            with connect() as db:
                for sql in (
                    "SELECT has_table_privilege(%s,%s,'SELECT')",
                    "SELECT has_table_privilege(%s,%s,'UPDATE')",
                ):
                    self.assertFalse(db.execute(sql, (role,TABLE)).fetchone()[0])
                self.assertFalse(db.execute(
                    "SELECT has_table_privilege(%s,%s,'SELECT')",
                    (role,VIEW)
                ).fetchone()[0])
                self.assertFalse(db.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')",
                    (role,FUNC+"(text,text,text,text,text,bigint,text)")
                ).fetchone()[0])
                db.execute("SET ROLE " + role)
                try:
                    for statement in (
                        "SELECT * FROM " + TABLE,
                        "SELECT * FROM " + VIEW,
                        "SELECT * FROM " + FUNC +
                        "('"+ACCOUNT+"','daily','SOL','long','"+"a"*32+"',1,'unknown_ack')",
                    ):
                        with self.subTest(statement=statement):
                            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                                db.execute(statement)
                finally:
                    db.execute("RESET ROLE")
        finally:
            with connect() as db:
                db.execute("DROP ROLE IF EXISTS " + role)

    def test_review_sql_never_exposes_order_execution_or_release_api(self):
        sql = SCRIPT.read_text("utf-8")
        self.assertIn("current_database() <> 'sender_review_test'", sql)
        self.assertIn("SECURITY INVOKER", sql)
        self.assertIn("security_invoker=true", sql)
        self.assertIn("BEFORE UPDATE OR DELETE", sql)
        self.assertNotIn("CREATE OR REPLACE FUNCTION sender_review_ci.release", sql)
        for disallowed in (
            "market_open(", "market_close(", "HL_PRIVATE_KEY",
            "submit_authorized", "retry_order(", "release_claim(",
        ):
            self.assertNotIn(disallowed, sql)


if __name__ == "__main__":
    unittest.main()
