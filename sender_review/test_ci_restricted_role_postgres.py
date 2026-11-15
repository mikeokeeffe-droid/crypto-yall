"""Disposable-only review of restricted PostgreSQL entrypoint permissions.

The role is NOLOGIN and has no real verified remote identity. This proves
database privilege separation, NOT workload authentication or trade safety.
"""
import concurrent.futures
import os
import unittest
import psycopg

from sender_review.test_ci_journal_postgres import CI_MARKER, SQL, connect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE_SQL = ROOT / "sender_review" / "ci_only_restricted_role.sql"
ROLE = "sender_review_ci_restricted"
ACCOUNT = "0x" + "1"*40


@unittest.skipUnless(
    os.environ.get(CI_MARKER) == "1"
    and os.environ.get("PGDATABASE") == "sender_review_test"
    and os.environ.get("PGHOST") == "127.0.0.1",
    "Disposable GitHub CI database only",
)
class RestrictedRoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connect() as c:
            c.execute(SQL.read_text("utf-8"))
            c.execute(ROLE_SQL.read_text("utf-8"))

    @classmethod
    def tearDownClass(cls):
        with connect() as c:
            c.execute(
                "REVOKE EXECUTE ON FUNCTION "
                "sender_review_ci.record_fixture_restricted("
                "text,text,text,text,text,numeric,integer,text) "
                "FROM sender_review_ci_restricted"
            )
            c.execute(
                "REVOKE USAGE ON SCHEMA sender_review_ci "
                "FROM sender_review_ci_restricted"
            )
            c.execute("DROP ROLE IF EXISTS sender_review_ci_restricted")

    def setUp(self):
        with connect() as c:
            c.execute(
                "TRUNCATE sender_review_ci.fixture_identity_receipts,"
                "sender_review_ci.review_events,"
                "sender_review_ci.review_intents,"
                "sender_review_ci.scope_fences RESTART IDENTITY CASCADE"
            )

    @staticmethod
    def call(jti="fixture-001", bot="daily", coin="SOL", nonce="a"*32):
        with connect() as c:
            c.execute("SET ROLE sender_review_ci_restricted")
            result = c.execute(
                "SELECT recorded,assigned_fence,reason "
                "FROM sender_review_ci.record_fixture_restricted("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                (jti,bot,coin,"open_long","long","0.16",2,nonce),
            ).fetchone()
            c.execute("RESET ROLE")
            return result

    @staticmethod
    def rows(sql):
        with connect() as c:
            return c.execute(sql).fetchall()

    def test_no_direct_write_read_or_other_functions(self):
        with connect() as c:
            self.assertEqual(c.execute(
                "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole "
                "FROM pg_roles WHERE rolname=%s", (ROLE,),
            ).fetchone(), (False,False,False,False))
            for table in ("fixture_identity_receipts","review_intents",
                          "review_events","scope_fences"):
                for permission in ("SELECT","INSERT","UPDATE","DELETE"):
                    with self.subTest(table=table,permission=permission):
                        allowed=c.execute(
                            "SELECT has_table_privilege(%s,%s,%s)",
                            (ROLE,"sender_review_ci."+table,permission),
                        ).fetchone()[0]
                        self.assertFalse(allowed)
            self.assertFalse(c.execute(
                "SELECT has_function_privilege(%s,"
                "'sender_review_ci.record_review_only("
                "text,text,text,text,text,numeric,integer,text)', 'EXECUTE')",
                (ROLE,),
            ).fetchone()[0])
            self.assertFalse(c.execute(
                "SELECT has_function_privilege(%s,"
                "'sender_review_ci.hold_uncertain(text,text,text,bigint)',"
                "'EXECUTE')", (ROLE,),
            ).fetchone()[0])
            self.assertTrue(c.execute(
                "SELECT has_function_privilege(%s,"
                "'sender_review_ci.record_fixture_restricted("
                "text,text,text,text,text,numeric,integer,text)', 'EXECUTE')",
                (ROLE,),
            ).fetchone()[0])
            c.execute("SET ROLE sender_review_ci_restricted")
            try:
                for sql in (
                    "SELECT * FROM sender_review_ci.review_intents",
                    "UPDATE sender_review_ci.scope_fences SET fence=42",
                    "INSERT INTO sender_review_ci.fixture_identity_receipts "
                    "(environment,account,jti,bot,request_nonce) VALUES "
                    "('testnet','" + ACCOUNT + "','fixture-001','daily','" + "a"*32 + "')",
                    "SELECT sender_review_ci.hold_uncertain("
                    "'" + ACCOUNT + "','SOL','" + "a"*32 + "',1)",
                ):
                    with self.subTest(sql=sql):
                        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                            c.execute(sql)
            finally:
                c.execute("RESET ROLE")

    def test_fixture_review_only_and_durable_replay(self):
        first=self.call()
        self.assertEqual(first,(True,1,"persisted-fixture-review-only-HOLD"))
        self.assertEqual(self.call()[0],False)
        self.assertEqual(self.call(jti="fixture-001",nonce="b"*32)[0],False)
        self.assertEqual(len(self.rows(
            "SELECT 1 FROM sender_review_ci.review_intents"
        )),1)
        self.assertEqual(len(self.rows(
            "SELECT 1 FROM sender_review_ci.fixture_identity_receipts"
        )),1)

    def test_competition_never_consumes_second_receipt(self):
        self.assertTrue(self.call()[0])
        denied=self.call(jti="fixture-002",bot="intraday",nonce="b"*32)
        self.assertFalse(denied[0])
        self.assertIn("journal-denied",denied[2])
        self.assertEqual(len(self.rows(
            "SELECT 1 FROM sender_review_ci.fixture_identity_receipts"
        )),1)

    def test_all_three_bots_race_only_one_records(self):
        jobs=[("daily","fixture-001","a"*32),
              ("intraday","fixture-002","b"*32),
              ("aggressive","fixture-003","c"*32)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            outcomes=list(pool.map(
                lambda item:self.call(jti=item[1],bot=item[0],nonce=item[2]),
                jobs,
            ))
        self.assertEqual(sum(int(x[0]) for x in outcomes),1)
        self.assertEqual(len(self.rows(
            "SELECT 1 FROM sender_review_ci.review_intents"
        )),1)

    def test_invalid_identity_creates_no_receipt(self):
        for jti,bot in (("","daily"),("bad space","daily"),
                        ("fixture-001","other")):
            with self.subTest(jti=jti,bot=bot):
                self.assertFalse(self.call(jti=jti,bot=bot)[0])
        self.assertEqual(self.rows(
            "SELECT 1 FROM sender_review_ci.fixture_identity_receipts"
        ),[])

    def test_non_ci_database_guard_is_present(self):
        sql=ROLE_SQL.read_text("utf-8")
        self.assertIn("current_database() <> 'sender_review_test'",sql)
        self.assertIn("SECURITY DEFINER SET search_path = pg_catalog, pg_temp",sql)
        self.assertNotIn("market_open(",sql)
        self.assertNotIn("market_close(",sql)


if __name__ == "__main__":
    unittest.main()
