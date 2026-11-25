"""Disposable PostgreSQL integration for the simulated authenticated HTTP gateway."""
import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql

from staging_executor_http_gateway import (
    ENTRY_CLAIM_PATH,
    create_staging_executor_entry_app,
)

BOTS = ("aggressive", "intraday", "daily")
KEYS = {
    "aggressive": b"aggressive-postgres-test-key-at-least-32-bytes",
    "intraday": b"intraday-postgres-test-key-at-least-32-bytes",
    "daily": b"daily-postgres-test-key-at-least-32-bytes!!!",
}
ISSUER = "isolated-test-idp"
AUDIENCE = "isolated-test-executor-gateway"
IDENTITY_PREFLIGHT = (
    Path(__file__).resolve().parents[1]
    / "db/entry_reservation_identity_preflight_staging.sql"
).read_text()


def signed_token(bot):
    def encode(value):
        return base64.urlsafe_b64encode(
            json.dumps(value).encode("utf-8")
        ).rstrip(b"=").decode("ascii")

    header = encode({"alg": "HS256", "typ": "JWT"})
    payload = encode({
        "sub": "executor:" + bot,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "scope": "executor:entry",
        "iat": 90,
        "nbf": 90,
        "exp": 4102444800,
    })
    message = header + "." + payload
    signature = base64.urlsafe_b64encode(
        hmac.new(KEYS[bot], message.encode("ascii"), hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")
    return message + "." + signature


@unittest.skipUnless(os.getenv("ISOLATED_POSTGRES_CI") == "1",
                     "only run on disposable PostgreSQL CI")
class GatewayPostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.logins = {
            bot: f"gateway_{bot}_{uuid.uuid4().hex[:8]}" for bot in BOTS
        }
        cls.passwords = {
            bot: secrets.token_urlsafe(36) for bot in BOTS
        }
        cls.reconciler_logins = {
            bot: f"gateway_reconciler_{bot}_{uuid.uuid4().hex[:8]}"
            for bot in BOTS
        }
        cls.reconciler_passwords = {
            bot: secrets.token_urlsafe(36) for bot in BOTS
        }
        cls.admin = psycopg.connect(
            host=os.getenv("PGHOST", "localhost"),
            port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "safety_test"),
            user=os.getenv("PGUSER", "postgres"),
            password=os.environ["PGPASSWORD"],
            autocommit=True,
        )
        for bot in BOTS:
            login = cls.logins[bot]
            cls.admin.execute(
                sql.SQL("create role {} login password {}").format(
                    sql.Identifier(login), sql.Literal(cls.passwords[bot]))
            )
            cls.admin.execute(
                sql.SQL("grant bot_entry_executor_trial to {}").format(
                    sql.Identifier(login))
            )
            cls.admin.execute(
                "insert into public.bot_entry_executor_identities (bot, db_login) "
                "values (%s, %s)",
                (bot, login),
            )
            reconciler_login = cls.reconciler_logins[bot]
            cls.admin.execute(
                sql.SQL("create role {} login password {}").format(
                    sql.Identifier(reconciler_login),
                    sql.Literal(cls.reconciler_passwords[bot]),
                )
            )
            cls.admin.execute(
                sql.SQL("grant bot_reconciler to {}").format(
                    sql.Identifier(reconciler_login),
                )
            )
            cls.admin.execute(
                "insert into public.bot_reconciler_identities (bot, db_login) "
                "values (%s, %s)",
                (bot, reconciler_login),
            )

    @classmethod
    def tearDownClass(cls):
        cls.admin.execute(
            "delete from public.bot_entry_executor_identities where db_login = any(%s)",
            (list(cls.logins.values()),),
        )
        cls.admin.execute(
            "delete from public.bot_reconciler_identities where db_login = any(%s)",
            (list(cls.reconciler_logins.values()),),
        )
        for login in cls.logins.values():
            cls.admin.execute(
                sql.SQL("drop role if exists {}").format(sql.Identifier(login))
            )
        for login in cls.reconciler_logins.values():
            cls.admin.execute(
                sql.SQL("revoke bot_reconciler from {}").format(
                    sql.Identifier(login),
                )
            )
            cls.admin.execute(
                sql.SQL("drop role if exists {}").format(sql.Identifier(login))
            )
        cls.admin.close()

    def setUp(self):
        self.admin.execute(
            "truncate public.bot_entry_intents, public.bot_entry_reservations"
        )
        self.app = create_staging_executor_entry_app(
            signing_keys=KEYS,
            connection_factories={
                bot: (lambda bot=bot: self.connect_restricted(bot))
                for bot in BOTS
            },
            expected_logins=self.logins,
            issuer=ISSUER,
            audience=AUDIENCE,
        )

    def connect_restricted(self, bot):
        return psycopg.connect(
            host=os.getenv("PGHOST", "localhost"),
            port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "safety_test"),
            user=self.logins[bot],
            password=self.passwords[bot],
        )

    def post(self, bot, coin, action, token=None):
        payload = json.dumps({
            "bot": bot,
            "coin": coin,
            "action": action,
        }).encode("utf-8")
        environ = {
            "PATH_INFO": ENTRY_CLAIM_PATH,
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(payload)),
            "HTTP_AUTHORIZATION": "Bearer " + (token or signed_token(bot)),
            "wsgi.input": io.BytesIO(payload),
        }
        response = {}

        def start_response(status, headers):
            response["status"] = status

        body = b"".join(self.app(environ, start_response))
        response["body"] = json.loads(body)
        return response

    def test_each_bot_uses_its_own_login_and_conflicts_are_fenced(self):
        for bot, coin in zip(BOTS, ("ATOM", "SOL", "AVAX")):
            with self.subTest(bot=bot):
                result = self.post(bot, coin, "open_long")
                self.assertEqual(result["status"], "200 OK")
                self.assertEqual(result["body"], {
                    "reservation_claimed": True,
                    "intent_claimed": True,
                })

        conflict = self.post("daily", "ATOM", "open_short")
        self.assertEqual(conflict["status"], "409 Conflict")
        self.assertEqual(conflict["body"], {"error": "entry claim denied"})

        with psycopg.connect(
            host=os.getenv("PGHOST", "localhost"),
            port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "safety_test"),
            user=self.logins["intraday"],
            password=self.passwords["intraday"],
        ) as conn:
            self.assertFalse(conn.execute(
                "select has_function_privilege(current_user, "
                "'public.resolve_bot_entry_intent(text,text,uuid)', "
                "'EXECUTE')").fetchone()[0])

    def test_database_permission_failure_blocks_http_claim(self):
        self.admin.execute(
            "revoke execute on function "
            "public.try_reserve_bot_entry(text,text,uuid,integer) "
            "from bot_entry_executor_trial"
        )
        try:
            result = self.post("intraday", "DENIED", "open_long")
            self.assertEqual(result["status"], "503 Service Unavailable")
            self.assertEqual(result["body"], {"error": "database unavailable"})
            self.assertFalse(self.admin.execute(
                "select exists (select 1 from public.bot_entry_reservations "
                "where coin = 'DENIED')"
            ).fetchone()[0])
        finally:
            self.admin.execute(
                "grant execute on function "
                "public.try_reserve_bot_entry(text,text,uuid,integer) "
                "to bot_entry_executor_trial"
            )

    def test_direct_postgres_rpcs_cannot_cross_bot_identity(self):
        coins = {
            "aggressive": "AGGR",
            "intraday": "INTR",
            "daily": "DAIL",
        }
        for bot in BOTS:
            own_token = uuid.uuid4()
            with self.subTest(bot=bot), self.connect_restricted(bot) as conn:
                self.assertEqual(
                    conn.execute(
                        "select session_user, current_user"
                    ).fetchone(),
                    (self.logins[bot], self.logins[bot]),
                )
                self.assertTrue(conn.execute(
                    "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                    (coins[bot], bot, own_token, 120),
                ).fetchone()[0])
                self.assertTrue(conn.execute(
                    "select public.claim_bot_entry_intent(%s,%s,%s)",
                    (coins[bot], bot, own_token),
                ).fetchone()[0])

            for other_bot in BOTS:
                if other_bot == bot:
                    continue
                with self.subTest(login=bot, requested_bot=other_bot):
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        with self.connect_restricted(bot) as conn:
                            conn.execute(
                                "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                                (f"{coins[bot]}X", other_bot, uuid.uuid4(), 120),
                            )
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        with self.connect_restricted(bot) as conn:
                            conn.execute(
                                "select public.claim_bot_entry_intent(%s,%s,%s)",
                                (f"{coins[bot]}X", other_bot, uuid.uuid4()),
                            )
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        with self.connect_restricted(bot) as conn:
                            conn.execute(
                                "select public.release_bot_entry(%s,%s,%s)",
                                (coins[bot], other_bot, own_token),
                            )

        with self.admin.cursor() as cursor:
            self.assertEqual(
                cursor.execute(
                    "select bot from public.bot_entry_intents "
                    "where coin = any(%s) order by bot",
                    (list(coins.values()),),
                ).fetchall(),
                [(bot,) for bot in sorted(BOTS)],
            )

    def test_identity_preflight_accepts_only_the_three_mapped_logins(self):
        self.admin.execute(IDENTITY_PREFLIGHT)


if __name__ == "__main__":
    unittest.main()
