"""Isolated CI only: exercise executor transport with a real restricted LOGIN."""
import os
import secrets
import unittest
import uuid

import psycopg
from psycopg import sql
from trusted_executor_postgres_transport_staging import restricted_executor_rpc

ROLE = "executor_login_trial"


@unittest.skipUnless(os.getenv("ISOLATED_POSTGRES_CI") == "1",
                     "disposable PostgreSQL CI only")
class DedicatedExecutorLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(36)
        cls.admin = psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True)
        cls.admin.execute(sql.SQL("create role {} login password {}").format(
            sql.Identifier(ROLE), sql.Literal(cls.password)))
        cls.admin.execute(sql.SQL("grant bot_entry_executor_trial to {}").format(
            sql.Identifier(ROLE)))

    @classmethod
    def tearDownClass(cls):
        cls.admin.execute(sql.SQL("drop role if exists {}").format(
            sql.Identifier(ROLE)))
        cls.admin.close()

    def connect_restricted(self):
        return psycopg.connect(host="localhost", port=5432,
                               dbname="safety_test", user=ROLE,
                               password=self.password)

    def test_transport_reserves_and_claims_but_cannot_resolve(self):
        rpc = restricted_executor_rpc(
            self.connect_restricted, expected_login=ROLE)
        token = uuid.uuid4()
        reserve = dict(p_coin="XRP", p_bot="aggressive",
                       p_token=token, p_ttl_seconds=120)
        self.assertTrue(rpc("try_reserve_bot_entry", reserve))
        self.assertTrue(rpc("claim_bot_entry_intent", {
            k: reserve[k] for k in ("p_coin", "p_bot", "p_token")}))
        self.assertFalse(rpc("try_reserve_bot_entry", dict(
            reserve, p_bot="intraday", p_token=uuid.uuid4())))
        with self.assertRaises(PermissionError):
            rpc("resolve_bot_entry_intent", {})
        with self.connect_restricted() as conn:
            self.assertFalse(conn.execute(
                "select has_function_privilege(current_user, "
                "'public.resolve_bot_entry_intent(text,text,uuid)', "
                "'EXECUTE')").fetchone()[0])
            self.assertFalse(conn.execute(
                "select has_table_privilege(current_user, "
                "'public.bot_entry_intents', 'UPDATE')").fetchone()[0])

    def test_identity_matches_dedicated_login(self):
        with self.connect_restricted() as conn:
            self.assertEqual(conn.execute(
                "select session_user, current_user").fetchone(), (ROLE, ROLE))


if __name__ == "__main__":
    unittest.main()
