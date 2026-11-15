"""Prove untrusted PostgreSQL roles cannot access the CI-only sender journal.

Disposable PostgreSQL service ONLY; these tests do not configure production
roles, grant sender permissions, authenticate workers or authorize trades.
"""
import os
import unittest

import psycopg

from sender_review.test_ci_journal_postgres import CI_MARKER, SQL, connect

DENIED_ROLE = "sender_review_ci_untrusted"


@unittest.skipUnless(
    os.environ.get(CI_MARKER) == "1"
    and os.environ.get("PGDATABASE") == "sender_review_test"
    and os.environ.get("PGHOST") == "127.0.0.1",
    "Only disposable local PostgreSQL CI is permitted",
)
class JournalUntrustedRolePermissionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connect() as conn:
            conn.execute(SQL.read_text(encoding="utf-8"))
            present = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=%s)",
                (DENIED_ROLE,),
            ).fetchone()[0]
            if not present:
                conn.execute(
                    "CREATE ROLE sender_review_ci_untrusted NOLOGIN "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION "
                    "NOBYPASSRLS"
                )

    @classmethod
    def tearDownClass(cls):
        # Created only within disposable CI cluster, never a real DB.
        with connect() as conn:
            conn.execute("DROP ROLE IF EXISTS sender_review_ci_untrusted")

    def test_no_schema_table_sequence_or_function_privileges(self):
        with connect() as conn:
            checks = [
                ("SELECT has_schema_privilege(%s, 'sender_review_ci', 'USAGE')",
                 (DENIED_ROLE,)),
                ("SELECT has_schema_privilege(%s, 'sender_review_ci', 'CREATE')",
                 (DENIED_ROLE,)),
                ("SELECT has_table_privilege(%s, "
                 "'sender_review_ci.review_intents', 'SELECT')",
                 (DENIED_ROLE,)),
                ("SELECT has_table_privilege(%s, "
                 "'sender_review_ci.scope_fences', 'UPDATE')",
                 (DENIED_ROLE,)),
                ("SELECT has_table_privilege(%s, "
                 "'sender_review_ci.fixture_identity_receipts', 'INSERT')",
                 (DENIED_ROLE,)),
                ("SELECT has_function_privilege(%s, "
                 "'sender_review_ci.record_review_only("
                 "text,text,text,text,text,numeric,integer,text)', 'EXECUTE')",
                 (DENIED_ROLE,)),
                ("SELECT has_function_privilege(%s, "
                 "'sender_review_ci.hold_uncertain(text,text,text,bigint)', "
                 "'EXECUTE')",
                 (DENIED_ROLE,)),
            ]
            for sql, params in checks:
                with self.subTest(sql=sql):
                    self.assertIs(
                        conn.execute(sql, params).fetchone()[0], False,
                    )

    def test_untrusted_role_cannot_query_modify_or_call_functions(self):
        attempts = (
            "SELECT count(*) FROM sender_review_ci.review_intents",
            "SELECT count(*) FROM sender_review_ci.review_events",
            "SELECT count(*) FROM sender_review_ci.scope_fences",
            "SELECT count(*) FROM sender_review_ci.fixture_identity_receipts",
            "UPDATE sender_review_ci.scope_fences SET fence=fence+1 "
            "WHERE false",
            "INSERT INTO sender_review_ci.fixture_identity_receipts "
            "(environment,account,jti,bot,request_nonce) "
            "VALUES ('testnet','0x1111111111111111111111111111111111111111',"
            "'attacker_jti','daily','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')",
            "SELECT sender_review_ci.record_review_only("
            "'0x1111111111111111111111111111111111111111',"
            "'daily','SOL','open_long','long',0.16,2,"
            "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')",
            "SELECT sender_review_ci.hold_uncertain("
            "'0x1111111111111111111111111111111111111111',"
            "'SOL','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',1)",
            "CREATE TABLE sender_review_ci.untrusted_insert(x integer)",
        )
        with connect() as conn:
            conn.execute("SET ROLE sender_review_ci_untrusted")
            try:
                current = conn.execute("SELECT current_user").fetchone()[0]
                self.assertEqual(current, DENIED_ROLE)
                for sql in attempts:
                    with self.subTest(sql=sql):
                        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                            conn.execute(sql)
            finally:
                conn.execute("RESET ROLE")

    def test_review_schema_has_no_executable_sender_functions(self):
        with connect() as conn:
            functions = conn.execute(
                "SELECT proname FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='sender_review_ci' ORDER BY proname"
            ).fetchall()
        self.assertEqual(functions, [
            ("hold_uncertain",), ("record_review_only",),
        ])


if __name__ == "__main__":
    unittest.main()
