"""Disposable PostgreSQL tests for callable staging gateway host/client."""
import io
import json
import os
import secrets
import unittest
import uuid

import psycopg
from psycopg import sql

from staging_executor_gateway_host import (
    GatewayClientError,
    GatewayStartupError,
    create_staging_executor_gateway_host,
)

BOTS = ("aggressive", "intraday", "daily")
ISSUER = "host-test-issuer"
AUDIENCE = "host-test-audience"
SIGNING_REFS = {bot: f"synthetic/signing/{bot}" for bot in BOTS}
PASSWORD_REFS = {bot: f"synthetic/database/{bot}" for bot in BOTS}
LOGINS = {bot: f"host_{bot}_{uuid.uuid4().hex[:8]}" for bot in BOTS}


@unittest.skipUnless(os.getenv("ISOLATED_POSTGRES_CI") == "1",
                     "only run on disposable PostgreSQL CI")
class StagingExecutorGatewayHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.passwords = {bot: secrets.token_urlsafe(36) for bot in BOTS}
        cls.signing_keys = {
            bot: secrets.token_bytes(32) for bot in BOTS
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
            login = LOGINS[bot]
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

    @classmethod
    def tearDownClass(cls):
        cls.admin.execute(
            "delete from public.bot_entry_executor_identities where db_login = any(%s)",
            (list(LOGINS.values()),),
        )
        for login in LOGINS.values():
            cls.admin.execute(
                sql.SQL("drop role if exists {}").format(sql.Identifier(login))
            )
        cls.admin.close()

    def setUp(self):
        self.admin.execute(
            "truncate public.bot_entry_intents, public.bot_entry_reservations"
        )
        self.audit_events = []
        self.secret_values = {
            **{
                SIGNING_REFS[bot]: self.signing_keys[bot]
                for bot in BOTS
            },
            **{
                PASSWORD_REFS[bot]: self.passwords[bot]
                for bot in BOTS
            },
        }
        self.host = self.create_host()
        self.transport_timeouts = []

    def create_host(self, *, expected_logins=None, secret_provider=None):
        if secret_provider is None:
            secret_provider = self.secret_values.__getitem__

        def connection_factory_builder(
            *, bot, login, password, sslmode, connect_timeout,
            statement_timeout_ms, lock_timeout_ms,
        ):
            return lambda: psycopg.connect(
                host=os.getenv("PGHOST", "localhost"),
                port=int(os.getenv("PGPORT", "5432")),
                dbname=os.getenv("PGDATABASE", "safety_test"),
                user=login,
                password=password.decode("utf-8"),
                sslmode=sslmode,
                sslrootcert=os.environ["PGSSLROOTCERT"],
                connect_timeout=connect_timeout,
                options=(
                    f"-c statement_timeout={statement_timeout_ms} "
                    f"-c lock_timeout={lock_timeout_ms}"
                ),
            )

        return create_staging_executor_gateway_host(
            secret_provider=secret_provider,
            signing_key_refs=SIGNING_REFS,
            database_password_refs=PASSWORD_REFS,
            expected_logins=expected_logins or LOGINS,
            connection_factory_builder=connection_factory_builder,
            issuer=ISSUER,
            audience=AUDIENCE,
            audit_sink=self.audit_events.append,
        )

    def transport(self, *, method, path, headers, body, timeout):
        self.transport_timeouts.append(timeout)
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_TYPE": headers["Content-Type"],
            "CONTENT_LENGTH": str(len(body)),
            "HTTP_AUTHORIZATION": headers["Authorization"],
            "wsgi.input": io.BytesIO(body),
        }
        response = {}

        def start_response(status, response_headers):
            response["status"] = int(status.split(" ", 1)[0])

        response_body = b"".join(self.host.app(environ, start_response))
        return response["status"], response_body

    def test_three_dedicated_logins_claim_independently_and_audit_is_redacted(self):
        client = self.host.create_client(transport=self.transport)
        for bot, coin in zip(BOTS, ("ATOM", "SOL", "AVAX")):
            with self.subTest(bot=bot):
                result = client(bot=bot, coin=coin, action="open_long")
                self.assertEqual(result, {
                    "reservation_claimed": True,
                    "intent_claimed": True,
                })
        self.assertEqual(self.transport_timeouts, [3.0, 3.0, 3.0])
        self.assertEqual(
            self.admin.execute(
                "select count(*) from public.bot_entry_executor_identities"
            ).fetchone()[0],
            3,
        )
        self.assertEqual(
            self.admin.execute(
                "select count(*) from public.bot_entry_reservations "
                "where coin like 'PR38%'"
            ).fetchone()[0],
            0,
            "startup identity probes must roll back their test reservations",
        )
        self.assertEqual([event["bot"] for event in self.audit_events],
                         list(BOTS))
        for event in self.audit_events:
            self.assertEqual(set(event), {
                "timestamp", "request_id", "status", "bot", "action", "outcome",
            })
        serialized_events = json.dumps(self.audit_events)
        for secret in (*self.passwords.values(), *self.signing_keys.values()):
            secret_text = secret.hex() if isinstance(secret, bytes) else secret
            self.assertNotIn(secret_text, serialized_events)
        self.assertNotIn("Authorization", serialized_events)
        self.assertNotIn("ATOM", serialized_events)

    def test_invalid_token_and_database_permission_failures_are_denied(self):
        invalid_client = self.host.create_client(
            transport=self.transport,
            token_provider=lambda bot: "not-a-valid-token",
        )
        with self.assertRaises(GatewayClientError):
            invalid_client(bot="aggressive", coin="DENIED", action="open_long")
        self.assertFalse(self.admin.execute(
            "select exists (select 1 from public.bot_entry_reservations "
            "where coin = 'DENIED')"
        ).fetchone()[0])
        self.assertEqual(self.audit_events[-1]["status"], 401)

        self.admin.execute(
            "revoke execute on function "
            "public.try_reserve_bot_entry(text,text,uuid,integer) "
            "from bot_entry_executor_trial"
        )
        try:
            with self.assertRaises(GatewayClientError):
                self.host.create_client(transport=self.transport)(
                    bot="intraday", coin="DENIED", action="open_long"
                )
            self.assertEqual(self.audit_events[-1]["status"], 503)
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

        self.admin.execute(
            "revoke execute on function "
            "public.try_reserve_bot_entry(text,text,uuid,integer) "
            "from bot_entry_executor_trial"
        )
        try:
            with self.assertRaises(GatewayStartupError):
                self.create_host()
        finally:
            self.admin.execute(
                "grant execute on function "
                "public.try_reserve_bot_entry(text,text,uuid,integer) "
                "to bot_entry_executor_trial"
            )

    def test_missing_secret_wrong_identity_and_timeout_fail_closed(self):
        with self.assertRaises(GatewayStartupError):
            self.create_host(secret_provider=lambda ref: None)

        wrong_logins = dict(LOGINS)
        wrong_logins["intraday"] = LOGINS["aggressive"]
        with self.assertRaises(GatewayStartupError):
            self.create_host(expected_logins=wrong_logins)

        def timeout_transport(**request):
            raise TimeoutError("synthetic transport timeout")

        client = self.host.create_client(transport=timeout_transport)
        with self.assertRaises(GatewayClientError):
            client(bot="daily", coin="TIMEOUT", action="open_short")

    def test_client_rejects_oversized_coin_before_transport(self):
        calls = []
        client = self.host.create_client(
            transport=lambda **request: calls.append(request)
        )
        with self.assertRaises(GatewayClientError):
            client(bot="daily", coin="X" * 5000, action="open_long")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
