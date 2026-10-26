"""Disposable PostgreSQL bridge test: signed gateway -> restricted DB identity.

No exchange connection, real credentials, HTTP server, or live order submission.
The RPC transport is injected and uses SET LOCAL ROLE inside a transaction.
"""
import base64
import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

import psycopg

from trusted_reconciler_authenticated_staging import reconcile_entry_with_token
from trusted_reconciler_worker_staging import ReconciliationResult

KEY = b"isolated-gateway-db-test-secret-32-bytes"
AUTH = dict(signing_key=KEY, issuer="isolated-issuer",
            audience="isolated-reconciler", now=100)
ENTRY = dict(coin="SOL", bot="intraday", token="00000000-0000-4000-8000-000000000001",
             order_id=17, order_start_ms=99000, clock=lambda: 100)


def signed_token(scope="reconciler:position-write"):
    def encode(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    header = encode({"alg": "HS256", "typ": "JWT"})
    body = encode({"sub": "isolated-worker", "iss": AUTH["issuer"],
                   "aud": AUTH["audience"], "scope": scope,
                   "iat": 90, "nbf": 90, "exp": 200})
    message = header + "." + body
    sig = base64.urlsafe_b64encode(
        hmac.new(KEY, message.encode("ascii"), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return message + "." + sig


def connect():
    return psycopg.connect(host=os.getenv("PGHOST", "localhost"),
                           port=int(os.getenv("PGPORT", "5432")),
                           dbname=os.getenv("PGDATABASE", "safety_test"),
                           user=os.getenv("PGUSER", "postgres"),
                           password=os.getenv("PGPASSWORD", "postgres"))


class GatewayDatabaseBoundaryTests(unittest.TestCase):
    def test_invalid_identity_never_reaches_exchange_or_database(self):
        calls = []
        with patch("trusted_reconciler_service_staging.reconcile_entry") as evidence:
            with self.assertRaises(PermissionError):
                reconcile_entry_with_token(None, None,
                    lambda *args: calls.append(args),
                    auth_token=signed_token("executor:reserve"), **AUTH, **ENTRY)
            evidence.assert_not_called()
        self.assertEqual(calls, [])

    def test_valid_identity_uses_only_reconciler_db_role(self):
        calls = []
        def restricted_rpc(function, params):
            calls.append(function)
            self.assertEqual(function, "record_bot_position_owner")
            with connect() as conn:
                with conn.transaction():
                    conn.execute("set local role bot_reconciler")
                    self.assertEqual(conn.execute("select current_user").fetchone()[0],
                                     "bot_reconciler")
                    self.assertTrue(conn.execute(
                        "select has_function_privilege(current_user, "
                        "'public.record_bot_position_owner(text,text,uuid,text,boolean)', "
                        "'EXECUTE')").fetchone()[0])
                    self.assertFalse(conn.execute(
                        "select has_function_privilege(current_user, "
                        "'public.try_reserve_bot_entry(text,text,uuid,integer)', "
                        "'EXECUTE')").fetchone()[0])
                    self.assertFalse(conn.execute(
                        "select has_table_privilege(current_user, "
                        "'public.bot_position_owners', 'UPDATE')").fetchone()[0])
            # No ownership mutation: isolated permission-boundary probe only.
            return False

        with patch("trusted_reconciler_service_staging.reconcile_entry",
                   return_value=ReconciliationResult(
                       "handoff_candidate", "mock verified evidence")):
            result = reconcile_entry_with_token(
                None, None, restricted_rpc,
                auth_token=signed_token(), **AUTH, **ENTRY)
        self.assertFalse(result.confirmed)
        self.assertEqual(calls, ["record_bot_position_owner"])


    def test_reconciler_direct_write_is_denied_by_database(self):
        with connect() as conn:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute("set local role bot_reconciler")
                    conn.execute(
                        "update public.bot_position_owners set bot=bot where false"
                    )

    def test_connection_failure_retains_intent_and_never_confirms_handoff(self):
        calls = []
        def unavailable_rpc(function, params):
            calls.append(function)
            raise psycopg.OperationalError("simulated isolated DB outage")

        with patch("trusted_reconciler_service_staging.reconcile_entry",
                   return_value=ReconciliationResult(
                       "handoff_candidate", "mock verified evidence")):
            result = reconcile_entry_with_token(
                None, None, unavailable_rpc,
                auth_token=signed_token(), **AUTH, **ENTRY)
        self.assertFalse(result.confirmed)
        self.assertIn("retain intent", result.reason)
        self.assertEqual(calls, ["record_bot_position_owner"])

if __name__ == "__main__":
    unittest.main()
