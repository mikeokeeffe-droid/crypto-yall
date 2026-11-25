"""Simulated WSGI requests with fake per-bot database credentials."""
import base64
import hashlib
import hmac
import io
import json
import unittest

from staging_executor_http_gateway import (
    ENTRY_CLAIM_PATH,
    StagingExecutorEntryApp,
)

BOTS = ("aggressive", "intraday", "daily")
KEYS = {
    "aggressive": b"aggressive-http-test-key-at-least-32-bytes",
    "intraday": b"intraday-http-test-key-at-least-32-bytes!!",
    "daily": b"daily-http-test-key-at-least-32-bytes!!!!!!",
}
ISSUER = "simulated-staging-idp"
AUDIENCE = "simulated-entry-gateway"


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


class Cursor:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value


class FakeConnection:
    def __init__(self, login, calls):
        self.login = login
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def transaction(self):
        return self

    def execute(self, query, params=None):
        self.calls.append((self.login, query, params))
        if query == "select session_user, current_user":
            return Cursor((self.login, self.login))
        return Cursor((True,))


class FakeDatabaseCredential:
    def __init__(self, login, password, calls):
        self.login = login
        self.password = password
        self.calls = calls

    def connect(self):
        return FakeConnection(self.login, self.calls)


class StagingExecutorHttpGatewayTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.credentials = {
            bot: FakeDatabaseCredential(
                f"staging_{bot}_login", f"fake-{bot}-password", self.calls
            )
            for bot in BOTS
        }
        self.app = StagingExecutorEntryApp(
            signing_keys=KEYS,
            connection_factories={
                bot: self.credentials[bot].connect for bot in BOTS
            },
            expected_logins={
                bot: self.credentials[bot].login for bot in BOTS
            },
            issuer=ISSUER,
            audience=AUDIENCE,
        )

    def request(self, payload, token=None, **environ_updates):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        environ = {
            "PATH_INFO": ENTRY_CLAIM_PATH,
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(body)),
            "HTTP_AUTHORIZATION": "Bearer " + token if token else "",
            "wsgi.input": io.BytesIO(body),
        }
        environ.update(environ_updates)
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        response = b"".join(self.app(environ, start_response))
        captured["body"] = json.loads(response)
        return captured

    def test_all_bots_are_bound_to_their_own_key_and_login(self):
        for bot in BOTS:
            with self.subTest(bot=bot):
                result = self.request(
                    {"bot": bot, "coin": "BTC", "action": "open_long"},
                    signed_token(bot),
                )
                self.assertEqual(result["status"], "200 OK")
                self.assertEqual(result["body"], {
                    "reservation_claimed": True,
                    "intent_claimed": True,
                })
                logins = {login for login, _, _ in self.calls}
                self.assertEqual(logins, {self.credentials[bot].login})
                self.assertNotIn(self.credentials[bot].password, result["body"].values())
                self.calls.clear()

    def test_invalid_or_cross_bot_tokens_never_reach_database(self):
        for bot, token in (
            ("intraday", signed_token("daily")),
            ("aggressive", "invalid.token.value"),
        ):
            with self.subTest(bot=bot):
                result = self.request(
                    {"bot": bot, "coin": "ETH", "action": "open_short"}, token
                )
                self.assertEqual(result["status"], "401 Unauthorized")
                self.assertEqual(result["headers"]["WWW-Authenticate"], "Bearer")
                self.assertEqual(self.calls, [])

    def test_malformed_or_client_supplied_server_fields_are_rejected(self):
        for field, value in (
            ("database_password", "fake-secret"),
            ("database_credentials", {"username": "fake", "password": "fake"}),
            ("signing_keys", {"intraday": "fake-secret"}),
            ("rpc", "claim_bot_entry_intent"),
        ):
            with self.subTest(field=field):
                payload = {
                    "bot": "intraday",
                    "coin": "SOL",
                    "action": "open_long",
                    field: value,
                }
                result = self.request(payload, signed_token("intraday"))
                self.assertEqual(result["status"], "400 Bad Request")
                self.assertEqual(self.calls, [])

        duplicate_fields = (
            b'{"bot":"intraday","bot":"daily","coin":"SOL","action":"open_long"}'
        )
        result = self.request(duplicate_fields, signed_token("intraday"))
        self.assertEqual(result["status"], "400 Bad Request")
        self.assertEqual(self.calls, [])

    def test_unauthorized_action_is_forbidden_without_database_access(self):
        result = self.request(
            {"bot": "daily", "coin": "BTC", "action": "close"},
            signed_token("daily"),
        )
        self.assertEqual(result["status"], "403 Forbidden")
        self.assertEqual(self.calls, [])

    def test_database_failure_returns_unavailable_without_details(self):
        def unavailable():
            raise OSError("fake password must not appear in responses")

        app = StagingExecutorEntryApp(
            signing_keys=KEYS,
            connection_factories={
                bot: (unavailable if bot == "intraday"
                      else self.credentials[bot].connect)
                for bot in BOTS
            },
            expected_logins={
                bot: self.credentials[bot].login for bot in BOTS
            },
            issuer=ISSUER,
            audience=AUDIENCE,
        )
        self.app = app
        result = self.request(
            {"bot": "intraday", "coin": "XRP", "action": "open_short"},
            signed_token("intraday"),
        )
        self.assertEqual(result["status"], "503 Service Unavailable")
        self.assertEqual(result["body"], {"error": "database unavailable"})
        self.assertNotIn("fake password", result["body"].values())

    def test_mismatched_database_login_is_unavailable_and_never_runs_rpc(self):
        app = StagingExecutorEntryApp(
            signing_keys=KEYS,
            connection_factories={
                bot: (
                    lambda bot=bot: FakeConnection("wrong_login", self.calls)
                    if bot == "intraday"
                    else self.credentials[bot].connect()
                )
                for bot in BOTS
            },
            expected_logins={
                bot: self.credentials[bot].login for bot in BOTS
            },
            issuer=ISSUER,
            audience=AUDIENCE,
        )
        self.app = app
        result = self.request(
            {"bot": "intraday", "coin": "ADA", "action": "open_long"},
            signed_token("intraday"),
        )
        self.assertEqual(result["status"], "503 Service Unavailable")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1], "select session_user, current_user")

    def test_duplicate_login_or_signing_key_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            StagingExecutorEntryApp(
                signing_keys=KEYS,
                connection_factories={
                    bot: self.credentials[bot].connect for bot in BOTS
                },
                expected_logins={bot: "shared_login" for bot in BOTS},
                issuer=ISSUER,
                audience=AUDIENCE,
            )
        with self.assertRaises(ValueError):
            StagingExecutorEntryApp(
                signing_keys={bot: KEYS["intraday"] for bot in BOTS},
                connection_factories={
                    bot: self.credentials[bot].connect for bot in BOTS
                },
                expected_logins={
                    bot: self.credentials[bot].login for bot in BOTS
                },
                issuer=ISSUER,
                audience=AUDIENCE,
            )

    def test_wrong_path_method_and_oversized_body_are_rejected(self):
        result = self.request(
            {"bot": "aggressive", "coin": "BTC", "action": "open_long"},
            signed_token("aggressive"),
            PATH_INFO="/",
        )
        self.assertEqual(result["status"], "404 Not Found")
        result = self.request(
            {"bot": "aggressive", "coin": "BTC", "action": "open_long"},
            signed_token("aggressive"),
            REQUEST_METHOD="GET",
        )
        self.assertEqual(result["status"], "405 Method Not Allowed")
        result = self.request(
            b"x" * 4097,
            signed_token("aggressive"),
        )
        self.assertEqual(result["status"], "400 Bad Request")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
