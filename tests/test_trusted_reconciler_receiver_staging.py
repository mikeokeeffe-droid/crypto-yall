"""Offline WSGI checks for the authenticated staging reconciliation receiver."""
import base64
import hashlib
import hmac
import io
import json
import unittest
import uuid

from staging_executor_gateway_contract import BOTS
from trusted_reconciler_receiver_staging import (
    RECONCILIATION_PATH,
    create_staging_reconciliation_receiver,
)

BOTS_ORDERED = ("aggressive", "intraday", "daily")
ISSUER = "synthetic-reconciler-issuer"
AUDIENCE = "synthetic-reconciler-receiver"
KEYS = {
    bot: f"offline-reconciler-{bot}-key-at-least-32-bytes".encode()
    for bot in BOTS
}


def signed_token(bot, *, key=None, subject=None, scope="reconciler:position-write"):
    def encode(value):
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        ).rstrip(b"=").decode()

    header = encode({"alg": "HS256", "typ": "JWT"})
    claims = encode({
        "aud": AUDIENCE,
        "exp": 200,
        "iat": 90,
        "iss": ISSUER,
        "nbf": 90,
        "scope": scope,
        "sub": subject or "reconciler:" + bot,
    })
    message = header + "." + claims
    signature = hmac.new(
        KEYS[bot] if key is None else key,
        message.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return message + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


class Cursor:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value


class FakeDatabaseConnection:
    def __init__(self, login, calls, *, intent):
        self.login = login
        self.calls = calls
        self.intent = intent

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def transaction(self):
        return self

    def execute(self, query, params=None):
        self.calls.append((self.login, query, params))
        if "where r.rolname = session_user" in query:
            return Cursor((
                self.login, self.login, True, False, True, False, False,
                False, False, True, True, True,
            ))
        if "has_function_privilege(current_user" in query:
            return Cursor((True,))
        if query == "select session_user, current_user":
            return Cursor((self.login, self.login))
        if "get_bot_entry_reconciliation_intent" in query:
            return Cursor(self.intent)
        return Cursor((True,))


class FakeExchange:
    def __init__(self):
        self.calls = []

    def order_status(self, address, order_id):
        self.calls.append("order_status")
        return {
            "status": "order",
            "order": {
                "order": {"coin": "SOL", "oid": "701"},
                "status": "canceled",
            },
        }

    def user_state(self, address):
        self.calls.append("user_state")
        return {"assetPositions": []}

    def open_orders(self, address):
        self.calls.append("open_orders")
        return []

    def user_fills(self, address):
        self.calls.append("user_fills")
        return []

    def user_fills_by_time(self, address, start_ms, end_ms):
        self.calls.append("user_fills_by_time")
        return []


class ReconciliationReceiverTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.intent = ("submitted", "701", 99_000, 2)
        self.logins = {
            bot: f"synthetic_reconciler_{bot}" for bot in BOTS_ORDERED
        }
        self.exchanges = {bot: FakeExchange() for bot in BOTS_ORDERED}
        self.audit = []

        def connection_factory(bot):
            return lambda: FakeDatabaseConnection(
                self.logins[bot], self.calls, intent=self.intent,
            )

        self.receiver = create_staging_reconciliation_receiver(
            signing_keys=KEYS,
            issuer=ISSUER,
            audience=AUDIENCE,
            info_clients=self.exchanges,
            account_addresses={
                bot: "0x" + "a" * 40 for bot in BOTS_ORDERED
            },
            connection_factories={
                bot: connection_factory(bot) for bot in BOTS_ORDERED
            },
            expected_logins=self.logins,
            audit_sink=self.audit.append,
            now=lambda: 100,
            clock=lambda: 100,
        )
        self.calls.clear()

    def request(self, payload, token=None, *, app=None, path=RECONCILIATION_PATH,
                method="POST", content_type="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": str(len(body)),
            "HTTP_AUTHORIZATION": "Bearer " + token if token else "",
            "wsgi.input": io.BytesIO(body),
        }
        response = {}

        def start_response(status, headers):
            response["status"] = status
            response["headers"] = dict(headers)

        response["body"] = json.loads(b"".join(
            (self.receiver if app is None else app)(environ, start_response)
        ))
        return response

    def payload(self, **overrides):
        result = {
            "bot": "intraday",
            "operation": "reconcile_entry",
            "coin": "SOL",
            "intent_token": str(uuid.UUID(
                "00000000-0000-4000-8000-000000000701"
            )),
        }
        result.update(overrides)
        return result

    def test_valid_bot_token_uses_server_exchange_and_reconciler_login(self):
        response = self.request(self.payload(), signed_token("intraday"))
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(response["body"], {"confirmed": True})
        self.assertEqual(self.exchanges["intraday"].calls.count("order_status"), 5)
        self.assertEqual(self.exchanges["aggressive"].calls, [])
        self.assertEqual(self.exchanges["daily"].calls, [])
        rpc_names = [query for _, query, _ in self.calls]
        self.assertTrue(any("get_bot_entry_reconciliation_intent" in q for q in rpc_names))
        self.assertTrue(any("release_resolved_bot_entry_intent" in q for q in rpc_names))
        self.assertEqual(
            {login for login, _, _ in self.calls},
            {"synthetic_reconciler_intraday"},
        )
        self.assertEqual(self.audit[-1]["outcome"], "confirmed")
        self.assertNotIn("SOL", json.dumps(self.audit[-1]))
        self.assertNotIn(self.payload()["intent_token"], json.dumps(self.audit[-1]))

    def test_cross_bot_token_and_caller_selected_credentials_or_rpcs_are_rejected(self):
        response = self.request(self.payload(), signed_token("daily"))
        self.assertEqual(response["status"], "401 Unauthorized")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.exchanges["intraday"].calls, [])

        for field, value in (
            ("database_password", "caller-secret"),
            ("connection_factory", "caller-controlled"),
            ("rpc", "release_closed_bot_position"),
            ("rpc_name", "release_closed_bot_position"),
            ("p_exchange_flat", True),
            ("p_no_open_orders", True),
        ):
            with self.subTest(field=field):
                response = self.request(
                    self.payload(**{field: value}),
                    signed_token("intraday"),
                )
                self.assertEqual(response["status"], "400 Bad Request")
                self.assertEqual(self.calls, [])
                self.assertEqual(self.exchanges["intraday"].calls, [])

    def test_database_failure_does_not_confirm_or_expose_error(self):
        connection_attempts = {"intraday": 0}

        factories = {
            bot: self._factory_failing_after_preflight(bot, connection_attempts)
            for bot in BOTS_ORDERED
        }
        receiver = create_staging_reconciliation_receiver(
            signing_keys=KEYS,
            issuer=ISSUER,
            audience=AUDIENCE,
            info_clients=self.exchanges,
            account_addresses={bot: "0x" + "a" * 40 for bot in BOTS_ORDERED},
            connection_factories=factories,
            expected_logins=self.logins,
            audit_sink=self.audit.append,
            now=lambda: 100,
            clock=lambda: 100,
        )
        response = self.request(
            self.payload(), signed_token("intraday"), app=receiver,
        )
        self.assertEqual(response["status"], "503 Service Unavailable")
        self.assertNotIn("synthetic database secret", json.dumps(response))
        self.assertEqual(self.exchanges["intraday"].calls, [])

    def _factory_failing_after_preflight(self, bot, attempts):
        def factory():
            if bot == "intraday":
                attempts[bot] += 1
                if attempts[bot] > 1:
                    raise OSError("synthetic database secret must not escape")
            return FakeDatabaseConnection(
                self.logins[bot], self.calls, intent=self.intent,
            )

        return factory

    def test_unresolved_or_uncertain_evidence_never_reports_confirmation(self):
        self.intent = ("uncertain", "701", 99_000, 2)
        exchange = self.exchanges["intraday"]
        original_status = exchange.order_status

        def unknown_order(address, order_id):
            result = original_status(address, order_id)
            result["order"]["status"] = "open"
            return result

        exchange.order_status = unknown_order
        response = self.request(self.payload(), signed_token("intraday"))
        self.assertEqual(response["status"], "409 Conflict")
        self.assertEqual(response["body"]["confirmed"], False)
        self.assertTrue(response["body"]["reconciliation_required"])
        self.assertFalse(any(
            "release_resolved_bot_entry_intent" in query
            for _, query, _ in self.calls
        ))

    def test_invalid_request_shapes_and_auth_header_fail_closed(self):
        for kwargs in (
            {"path": "/"},
            {"method": "GET"},
            {"content_type": "text/plain"},
        ):
            with self.subTest(kwargs=kwargs):
                response = self.request(
                    self.payload(), signed_token("intraday"), **kwargs,
                )
                self.assertEqual(response["status"], "400 Bad Request")
        extra = self.request(
            self.payload(caller_rpc="release_closed_bot_position"),
            signed_token("intraday"),
        )
        self.assertEqual(extra["status"], "400 Bad Request")
        bad_header = self.request(
            self.payload(), "Bearer " + signed_token("intraday"),
        )
        self.assertEqual(bad_header["status"], "401 Unauthorized")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.exchanges["intraday"].calls, [])


if __name__ == "__main__":
    unittest.main()
