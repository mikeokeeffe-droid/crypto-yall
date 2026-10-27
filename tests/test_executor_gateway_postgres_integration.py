"""Disposable PostgreSQL CI: end-to-end staging gateway reservation claim."""
import os
import secrets
import unittest

import psycopg
from psycopg import sql

from trusted_executor_gateway_staging import stage_entry_claim
from trusted_executor_postgres_transport_staging import restricted_executor_rpc

ROLE = "gateway_executor_login_trial"


@unittest.skipUnless(os.getenv("ISOLATED_POSTGRES_CI") == "1",
                     "only run on disposable PostgreSQL CI")
class GatewayPostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(36)
        cls.admin = psycopg.connect(host="localhost", port=5432,
                                    dbname="safety_test", user="postgres",
                                    password=os.environ["PGPASSWORD"],
                                    autocommit=True)
        cls.admin.execute(sql.SQL("create role {} login password {}").format(
            sql.Identifier(ROLE), sql.Literal(cls.password)))
        cls.admin.execute(sql.SQL("grant bot_entry_executor_trial to {}").format(
            sql.Identifier(ROLE)))

    @classmethod
    def tearDownClass(cls):
        cls.admin.execute(sql.SQL("drop role if exists {}").format(sql.Identifier(ROLE)))
        cls.admin.close()

    def connect_restricted(self):
        return psycopg.connect(host="localhost", port=5432,
                               dbname="safety_test", user=ROLE,
                               password=self.password)

    def test_verified_intraday_claim_blocks_competing_daily(self):
        rpc = restricted_executor_rpc(self.connect_restricted, expected_login=ROLE)
        verify_intraday = lambda _: {"subject": "executor:intraday",
                                     "scope": "executor:entry", "verified": True}
        claim = stage_entry_claim(jwt_token="offline-test", bot="intraday",
                                  coin="ATOM", action="open_long",
                                  verify_token=verify_intraday, rpc=rpc)
        self.assertTrue(claim.claimed)
        self.assertFalse(claim.live_order_authorized)
        verify_daily = lambda _: {"subject": "executor:daily",
                                  "scope": "executor:entry", "verified": True}
        with self.assertRaises(PermissionError):
            stage_entry_claim(jwt_token="offline-test", bot="daily",
                              coin="ATOM", action="open_short",
                              verify_token=verify_daily, rpc=rpc)
        with self.connect_restricted() as conn:
            self.assertFalse(conn.execute(
                "select has_function_privilege(current_user, "
                "'public.resolve_bot_entry_intent(text,text,uuid)', "
                "'EXECUTE')").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
