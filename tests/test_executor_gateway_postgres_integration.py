"""Disposable PostgreSQL CI: end-to-end staging gateway reservation claim."""
import os
import secrets
import unittest
import base64
import hashlib
import hmac
import json

import psycopg
from psycopg import sql

from trusted_executor_gateway_staging import stage_entry_claim
from trusted_executor_postgres_transport_staging import restricted_executor_rpc

ROLE = "gateway_executor_login_trial"
KEYS = {
    "aggressive": b"aggressive-postgres-test-key-at-least-32-bytes",
    "intraday": b"intraday-postgres-test-key-at-least-32-bytes",
    "daily": b"daily-postgres-test-key-at-least-32-bytes!!!",
}
ISSUER = "isolated-test-idp"
AUDIENCE = "isolated-test-executor-gateway"


def signed_token(bot):
    def encode(value):
        return base64.urlsafe_b64encode(
            json.dumps(value).encode()).rstrip(b"=").decode()

    header = encode({"alg": "HS256", "typ": "JWT"})
    payload = encode({"sub": "executor:" + bot, "iss": ISSUER,
                      "aud": AUDIENCE, "scope": "executor:entry",
                      "iat": 90, "nbf": 90, "exp": 200})
    signing_input = header + "." + payload
    signature = base64.urlsafe_b64encode(
        hmac.new(KEYS[bot], signing_input.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return signing_input + "." + signature


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
        claim = stage_entry_claim(jwt_token=signed_token("intraday"), bot="intraday",
                                  coin="ATOM", action="open_long",
                                  signing_keys=KEYS, issuer=ISSUER,
                                  audience=AUDIENCE, now=100, rpc=rpc)
        self.assertTrue(claim.claimed)
        self.assertFalse(claim.live_order_authorized)
        with self.assertRaises(PermissionError):
            stage_entry_claim(jwt_token=signed_token("daily"), bot="daily",
                              coin="ATOM", action="open_short",
                              signing_keys=KEYS, issuer=ISSUER,
                              audience=AUDIENCE, now=100, rpc=rpc)
        with self.connect_restricted() as conn:
            self.assertFalse(conn.execute(
                "select has_function_privilege(current_user, "
                "'public.resolve_bot_entry_intent(text,text,uuid)', "
                "'EXECUTE')").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
