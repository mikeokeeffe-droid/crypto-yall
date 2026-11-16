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


if __name__ == "__main__":
    unittest.main()
