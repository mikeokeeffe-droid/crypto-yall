"""In-process ASGI only: no listener, network, database, secrets or trades."""
import asyncio
import json
import unittest
from unittest.mock import patch

from sender_review.asgi_review_only_ingress import application
from sender_review.test_remote_request_boundary_offline import (
    OfflineRemoteRequestBoundaryTests,
)


class ReviewOnlyAsgiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OfflineRemoteRequestBoundaryTests.setUpClass()
        cls.fixture = OfflineRemoteRequestBoundaryTests()

    def request(self, *, method="POST", path="/v1/review-only/entry-intents",
                headers=None, body=None, messages=None, scope_changes=None):
        if body is None:
            body = self.fixture.body()
        if headers is None:
            headers = [
                (b"content-type", b"application/json"),
                (b"authorization", ("Bearer " + self.fixture.token()).encode()),
                (b"content-length", str(len(body)).encode()),
            ]
        scope = {
            "type": "http", "method": method, "path": path,
            "raw_path": path.encode(), "query_string": b"",
            "headers": headers,
        }
        scope.update(scope_changes or {})
        stream = list(messages) if messages is not None else [
            {"type": "http.request", "body": body, "more_body": False},
        ]
        responses = []

        async def receive():
            if not stream:
                raise AssertionError("unexpected extra receive")
            return stream.pop(0)

        async def send(message):
            responses.append(message)

        with patch(
            "sender_review.asgi_review_only_ingress."
            "inspect_server_oidc_preflight_review",
            return_value=None,
        ) as preflight:
            asyncio.run(application(scope, receive, send))
        if not responses:
            return None, None, preflight
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["type"], "http.response.start")
        self.assertEqual(responses[1]["type"], "http.response.body")
        decoded = json.loads(responses[1]["body"])
        self.assertEqual(decoded["state"], "HOLD")
        self.assertNotIn(self.fixture.token(), repr(responses))
        return responses[0]["status"], decoded, preflight

    def test_valid_three_bot_envelopes_still_unavailable(self):
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                token = self.fixture.token(bot)
                body = self.fixture.body()
                status, result, preflight = self.request(headers=[
                    (b"authorization", ("Bearer " + token).encode()),
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ], body=body)
                self.assertEqual(status, 503)
                self.assertEqual(result["reason"], "no authenticated sender deployed")
                self.assertEqual(preflight.call_count, 1)
                self.assertIs(preflight.call_args.kwargs[
                    "approved_readonly_key_fetch"], False)

    def test_invalid_route_method_headers_body_fail_before_preflight(self):
        valid_body = self.fixture.body()
        token = self.fixture.token()
        h = [(b"authorization", ("Bearer " + token).encode()),
             (b"content-type", b"application/json")]
        cases = (
            {"method": "GET"},
            {"path": "/v1/orders"},
            {"scope_changes": {"query_string": b"go=true"}},
            {"headers": h + [(b"Authorization", ("Bearer " + token).encode())]},
            {"headers": h + [(b"x-authorize", b"true")]},
            {"headers": [(b"content-type", b"application/json")]},
            {"headers": [(b"authorization", b"Bearer invalid"),
                         (b"content-type", b"application/json")]},
            {"headers": [(b"authorization", ("Bearer " + token).encode()),
                         (b"content-type", b"text/plain")]},
            {"headers": h + [(b"content-length", b"1")]},
            {"body": self.fixture.body(submit_authorized=True)},
            {"body": b"x" * 1025},
            {"messages": [{"type": "http.request", "body": b"x" * 1025,
                           "more_body": False}]},
        )
        for kwargs in cases:
            with self.subTest(kwargs=str(kwargs)[:100]):
                status, result, preflight = self.request(**kwargs)
                self.assertIn(status, (400, 401, 404, 405, 413))
                self.assertEqual(preflight.call_count, 0)

    def test_chunked_body_and_disconnect(self):
        body = self.fixture.body()
        chunks = [
            {"type": "http.request", "body": body[:12], "more_body": True},
            {"type": "http.request", "body": body[12:], "more_body": False},
        ]
        status, _, preflight = self.request(
            messages=chunks,
        )
        self.assertEqual(status, 503)
        self.assertEqual(preflight.call_count, 1)
        status, _, preflight = self.request(messages=[
            {"type": "http.disconnect"},
        ])
        self.assertIsNone(status)
        self.assertEqual(preflight.call_count, 0)

    def test_stream_receive_exceptions_return_redacted_hold_without_preflight(self):
        token = self.fixture.token()
        body = self.fixture.body()
        scope = {
            "type": "http", "method": "POST",
            "path": "/v1/review-only/entry-intents",
            "raw_path": b"/v1/review-only/entry-intents",
            "query_string": b"",
            "headers": [
                (b"content-type", b"application/json"),
                (b"authorization", ("Bearer " + token).encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        }
        for failure in (RuntimeError("secret-token-not-for-response"),
                        ValueError("bad stream adapter")):
            for on_second_chunk in (False, True):
                with self.subTest(failure=type(failure).__name__,
                                  on_second_chunk=on_second_chunk):
                    result = []
                    times = 0

                    async def receive():
                        nonlocal times
                        times += 1
                        if on_second_chunk and times == 1:
                            return {
                                "type": "http.request",
                                "body": body[:10],
                                "more_body": True,
                            }
                        raise failure

                    async def send(message):
                        result.append(message)

                    with patch(
                        "sender_review.asgi_review_only_ingress."
                        "inspect_server_oidc_preflight_review",
                        side_effect=AssertionError("unexpected identity preflight"),
                    ) as preflight:
                        asyncio.run(application(scope, receive, send))
                    self.assertEqual(preflight.call_count, 0)
                    self.assertEqual(len(result), 2)
                    self.assertEqual(result[0]["status"], 503)
                    self.assertEqual(json.loads(result[1]["body"]), {
                        "state": "HOLD", "reason": "request stream unavailable"
                    })
                    self.assertNotIn(token, repr(result))
                    self.assertNotIn("secret-token", repr(result))

    def test_preflight_exception_returns_redacted_503_hold(self):
        # Exercise the actual ASGI callable, not the request() helper's mock.
        # A damaged identity preflight must neither escape nor expose a JWT.
        token = self.fixture.token()
        body = self.fixture.body()
        scope = {
            "type": "http", "method": "POST",
            "path": "/v1/review-only/entry-intents",
            "raw_path": b"/v1/review-only/entry-intents",
            "query_string": b"",
            "headers": [
                (b"content-type", b"application/json"),
                (b"authorization", ("Bearer " + token).encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        }
        async def exercise(mock_result=None, failure=None):
            response = []
            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}
            async def send(message):
                response.append(message)
            with patch(
                "sender_review.asgi_review_only_ingress."
                "inspect_server_oidc_preflight_review",
                return_value=mock_result, side_effect=failure,
            ) as mocked:
                await application(scope, receive, send)
            return response, mocked

        for failure in (RuntimeError("secret-token-do-not-leak"),
                        ValueError("untrusted-key-error")):
            with self.subTest(failure=type(failure).__name__):
                messages, mocked = asyncio.run(exercise(failure=failure))
                self.assertEqual(len(messages), 2)
                self.assertEqual(messages[0]["status"], 503)
                self.assertEqual(messages[0]["type"], "http.response.start")
                self.assertEqual(messages[1]["type"], "http.response.body")
                decoded = json.loads(messages[1]["body"])
                self.assertEqual(decoded, {
                    "state": "HOLD", "reason": "identity preflight unavailable",
                })
                self.assertEqual(mocked.call_count, 1)
                self.assertIs(mocked.call_args.kwargs[
                    "approved_readonly_key_fetch"], False)
                self.assertNotIn(token, repr(messages))
                self.assertNotIn("secret-token", repr(messages))

    def test_forged_successful_preflight_still_returns_503_hold(self):
        body = self.fixture.body()
        token = self.fixture.token()
        scope = {
            "type": "http", "method": "POST",
            "path": "/v1/review-only/entry-intents",
            "raw_path": b"/v1/review-only/entry-intents",
            "query_string": b"",
            "headers": [
                (b"content-type", b"application/json"),
                (b"authorization", ("Bearer " + token).encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        }
        responses = []
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        async def send(message):
            responses.append(message)
        # Even a deliberately forged diagnostic result is NOT permission.
        with patch(
            "sender_review.asgi_review_only_ingress."
            "inspect_server_oidc_preflight_review",
            return_value={"state": "APPROVED", "submit_authorized": True},
        ) as preflight:
            asyncio.run(application(scope, receive, send))
        self.assertEqual(preflight.call_count, 1)
        self.assertEqual(responses[0]["status"], 503)
        self.assertEqual(json.loads(responses[1]["body"]), {
            "state": "HOLD", "reason": "no authenticated sender deployed",
        })
        self.assertNotIn(token, repr(responses))

    def test_no_outbound_transport_possible_even_with_fake_preflight(self):
        body = self.fixture.body()
        with patch("sender_review.asgi_review_only_ingress."
                   "inspect_server_oidc_preflight_review",
                   side_effect=AssertionError("must not bypass wrapper")):
            # Invalid input is denied without an identity preflight at all.
            status, _, _ = self.request(
                body=self.fixture.body(action="market_open")
            )
            self.assertEqual(status, 400)


    def test_server_review_scope_rejects_mainnet_and_endpoint_drift(self):
        # A legitimate-looking request cannot override a broken/mutated
        # review-only server policy. It stays unavailable before preflight.
        for bot in ("daily", "intraday", "aggressive"):
            body = self.fixture.body()
            headers = [
                (b"authorization", ("Bearer " + self.fixture.token(bot)).encode()),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ]
            for network in ("mainnet", "MAINNET", "", "false", None):
                with self.subTest(bot=bot, network=network):
                    with patch(
                        "sender_review.asgi_review_only_ingress."
                        "_SERVER_REVIEW_NETWORK", network,
                    ):
                        status, response, preflight = self.request(
                            body=body, headers=headers,
                        )
                    self.assertEqual(status, 503)
                    self.assertEqual(
                        response["reason"],
                        "review-only Testnet policy unavailable",
                    )
                    self.assertEqual(preflight.call_count, 0)
            for endpoint in ("https://api.hyperliquid.xyz", "", None):
                with self.subTest(bot=bot, endpoint=endpoint):
                    with patch(
                        "sender_review.asgi_review_only_ingress."
                        "_SERVER_REVIEW_API_URL", endpoint,
                    ):
                        status, response, preflight = self.request(
                            body=body, headers=headers,
                        )
                    self.assertEqual(status, 503)
                    self.assertEqual(
                        response["reason"],
                        "review-only Testnet policy unavailable",
                    )
                    self.assertEqual(preflight.call_count, 0)

    def test_even_valid_testnet_scope_is_no_send_and_untrusted(self):
        # The fixed Testnet string is only a review proposal, not
        # operational source authentication or sender authorization.
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                token = self.fixture.token(bot)
                body = self.fixture.body()
                status, response, preflight = self.request(
                    headers=[
                        (b"authorization", ("Bearer " + token).encode()),
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                    body=body,
                )
                self.assertEqual(status, 503)
                self.assertEqual(
                    response["reason"], "no authenticated sender deployed",
                )
                self.assertEqual(preflight.call_count, 1)


if __name__ == "__main__":
    unittest.main()
