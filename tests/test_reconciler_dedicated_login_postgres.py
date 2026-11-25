"""Isolated CI only: prove a dedicated PostgreSQL LOGIN has restricted rights.

Creates a disposable principal with an ephemeral secret on local CI PostgreSQL.
Never connect to Supabase or production; requires explicit CI opt-in.
"""
import os
import secrets
import unittest
import psycopg
from psycopg import sql
from trusted_reconciler_postgres_transport_staging import restricted_reconciler_rpc

ROLE = "reconciler_login_trial"


@unittest.skipUnless(os.getenv("ISOLATED_POSTGRES_CI") == "1",
                     "only run on disposable PostgreSQL CI")
class DedicatedLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(36)
        cls.admin = psycopg.connect(
                                   host=os.getenv("PGHOST", "localhost"),
                                   port=int(os.getenv("PGPORT", "5432")),
                                   dbname=os.getenv("PGDATABASE", "safety_test"),
                                   user=os.getenv("PGUSER", "postgres"),
                                   password=os.environ["PGPASSWORD"],
                                   autocommit=True)
        cls.admin.execute(
            sql.SQL("create role {} login password {}").format(
                sql.Identifier(ROLE), sql.Literal(cls.password)))
        cls.admin.execute(sql.SQL("grant bot_reconciler to {}").format(
            sql.Identifier(ROLE)))

    @classmethod
    def tearDownClass(cls):
        cls.admin.execute(sql.SQL("drop role if exists {}").format(
            sql.Identifier(ROLE)))
        cls.admin.close()

    def connect_restricted(self):
        return psycopg.connect(host=os.getenv("PGHOST", "localhost"),
                               port=int(os.getenv("PGPORT", "5432")),
                               dbname=os.getenv("PGDATABASE", "safety_test"),
                               user=ROLE,
                               password=self.password)

    def test_distinct_login_and_no_executor_rights(self):
        with self.connect_restricted() as conn:
            self.assertEqual(conn.execute(
                "select session_user, current_user").fetchone(), (ROLE, ROLE))
            self.assertFalse(conn.execute(
                "select has_function_privilege(current_user, "
                "'public.try_reserve_bot_entry(text,text,uuid,integer)', "
                "'EXECUTE')").fetchone()[0])
            self.assertFalse(conn.execute(
                "select has_table_privilege(current_user, "
                "'public.bot_position_owners', 'UPDATE')").fetchone()[0])
            self.assertTrue(conn.execute(
                "select has_function_privilege(current_user, "
                "'public.record_bot_position_owner(text,text,uuid,text,boolean)', "
                "'EXECUTE')").fetchone()[0])

    def test_transport_enforces_real_login_and_blocks_unlisted_rpc(self):
        rpc = restricted_reconciler_rpc(
            self.connect_restricted, expected_login=ROLE)
        with self.assertRaises(PermissionError):
            rpc("try_reserve_bot_entry", {})
        with self.assertRaises(PermissionError):
            rpc("record_bot_position_owner", {"p_coin": "SOL"})

    def test_direct_table_mutation_is_denied(self):
        with self.connect_restricted() as conn:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute(
                        "update public.bot_position_owners set bot=bot where false")


if __name__ == "__main__":
    unittest.main()
