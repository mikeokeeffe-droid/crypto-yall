"""Disposable CI-only ASGI -> fake signed identity -> fenced journal test.

Uses in-process ASGI calls only; zero network listener or actual exchange.
Never return a successful HTTP order response, even when a fixture journal
record is persisted. Requires disposable loopback PostgreSQL CI marker.
"""
import asyncio
import json
import os
import unittest
from unittest.mock import patch

from sender_review.ci_only_asgi_journal_handoff import (
    inspect_asgi_to_disposable_journal_offline,
)
from sender_review.test_remote_request_boundary_offline import (
    OfflineRemoteRequestBoundaryTests, NOW,
)
from sender_review.test_ci_journal_postgres import (
    ACCOUNT, CI_MARKER, SQL, connect,
)


@unittest.skipUnless(
    os.environ.get(CI_MARKER) == "1"
    and os.environ.get("PGDATABASE") == "sender_review_test"
    and os.environ.get("PGHOST") == "127.0.0.1",
    "Disposable local PostgreSQL CI only",
)
class InProcessAsgiJournalHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OfflineRemoteRequestBoundaryTests.setUpClass()
        cls.fixtures = OfflineRemoteRequestBoundaryTests()
        cls.keys = OfflineRemoteRequestBoundaryTests.keys
        with connect() as db:
            db.execute(SQL.read_text(encoding="utf-8"))

    def setUp(self):
        with connect() as db:
            db.execute(
                "TRUNCATE sender_review_ci.fixture_identity_receipts,"
                "sender_review_ci.review_events,"
                "sender_review_ci.review_intents,"
                "sender_review_ci.scope_fences RESTART IDENTITY CASCADE"
            )

    def count(self, table):
        with connect() as db:
            return db.execute(
                "SELECT count(*) FROM sender_review_ci." + table
            ).fetchone()[0]

    def request(self, *, bot="daily", nonce="a"*32, coin="SOL",
                headers=None, body=None, path="/v1/review-only/entry-intents",
                method="POST"):
        if body is None:
            body = self.fixtures.body(coin=coin, request_nonce=nonce)
        token = self.fixtures.token(bot, jti="asgi-fixture-"+bot+"-"+nonce[:6])
        if headers is None:
            headers = [
                (b"content-type", b"application/json"),
                (b"authorization", ("Bearer " + token).encode()),
                (b"content-length", str(len(body)).encode()),
            ]
        scope = {
            "type": "http", "path": path, "raw_path": path.encode(),
            "method": method, "query_string": b"", "headers": headers,
        }
        async def run():
            messages=[]
            async def receive():
                return {"type": "http.request", "body": body,
                        "more_body": False}
            async def send(message):
                messages.append(message)
            result = await inspect_asgi_to_disposable_journal_offline(
                scope=scope, receive=receive, send=send,
                trusted_fixture_keys=self.keys, fixture_now_seconds=NOW,
                fixed_test_account=ACCOUNT,
                db_password=os.environ["PGPASSWORD"],
            )
            return result, messages
        result, messages = asyncio.run(run())
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["type"], "http.response.start")
        self.assertEqual(messages[1]["type"], "http.response.body")
        self.assertEqual(json.loads(messages[1]["body"])["state"], "HOLD")
        self.assertNotIn(token, repr(messages))
        for attribute in (
            "runtime_identity_authenticated", "request_authorized",
            "submit_authorized", "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, attribute), False, attribute)
        return result, messages

    def test_three_bot_entry_fixtures_journal_only_with_http_503(self):
        for bot, nonce in (
            ("daily", "a"*32), ("intraday", "b"*32),
            ("aggressive", "c"*32),
        ):
            with self.subTest(bot=bot):
                self.setUp()
                result, messages=self.request(bot=bot, nonce=nonce)
                self.assertTrue(result.journal_recorded)
                self.assertEqual(messages[0]["status"], 503)
                self.assertEqual(
                    json.loads(messages[1]["body"])["reason"],
                    "no authenticated sender deployed",
                )
                self.assertEqual(self.count("review_intents"), 1)
                with connect() as db:
                    self.assertEqual(db.execute(
                        "SELECT bot,state FROM sender_review_ci.review_intents"
                    ).fetchall(), [(bot, "review_only")])

    def test_competing_bot_same_coin_and_replay_are_denied(self):
        first, _ = self.request(bot="daily", nonce="a"*32)
        self.assertTrue(first.journal_recorded)
        replay, response = self.request(bot="daily", nonce="a"*32)
        self.assertFalse(replay.journal_recorded)
        self.assertEqual(response[0]["status"], 503)
        other, response = self.request(bot="intraday", nonce="b"*32)
        self.assertFalse(other.journal_recorded)
        self.assertEqual(response[0]["status"], 503)
        self.assertEqual(self.count("review_intents"), 1)
        self.assertEqual(self.count("fixture_identity_receipts"), 1)

    def test_malformed_or_unauthorized_inputs_never_record(self):
        token=self.fixtures.token("daily")
        malformed=(
            {"method": "GET"},
            {"path": "/v1/trade"},
            {"body": b"not json"},
            {"body": self.fixtures.body(action="protective_close")},
            {"headers": [
                (b"content-type", b"application/json"),
                (b"authorization", ("Bearer " + token).encode()),
                (b"authorization", ("Bearer " + token).encode()),
            ]},
        )
        for kwargs in malformed:
            with self.subTest(keys=tuple(kwargs)):
                result, response=self.request(**kwargs)
                self.assertFalse(result.journal_recorded)
                self.assertGreaterEqual(response[0]["status"], 400)
                self.assertEqual(self.count("review_intents"), 0)

    def test_malformed_or_spoofed_asgi_responses_never_record(self):
        # An unexpected response cannot be treated as a validation pass,
        # even if it contains the former review-only HOLD text.
        from sender_review import ci_only_asgi_journal_handoff as adapter
        original=self.fixtures.body()
        token=self.fixtures.token("daily")
        headers=[
            (b"content-type", b"application/json"),
            (b"authorization", ("Bearer " + token).encode()),
            (b"content-length", str(len(original)).encode()),
        ]
        scope={
            "type":"http", "method":"POST",
            "path":"/v1/review-only/entry-intents",
            "raw_path":b"/v1/review-only/entry-intents",
            "query_string":b"", "headers":headers,
        }
        hold=b'{"state":"HOLD","reason":"no authenticated sender deployed"}'
        variations=(
            [{"type":"http.response.body","body":hold},
             {"type":"http.response.start","status":503}],
            [{"type":"http.response.start","status":200},
             {"type":"http.response.body","body":hold}],
            [{"type":"http.response.start","status":503},
             {"type":"http.response.body","body":hold,"more_body":True}],
            [{"type":"http.response.start","status":503},
             {"type":"http.response.body","body":hold},
             {"type":"http.response.body","body":b"extra"}],
        )
        for outputs in variations:
            with self.subTest(outputs=outputs):
                async def fake_asgi(unused_scope, receive, send):
                    message=await receive()
                    self.assertEqual(message["body"], original)
                    for output in outputs:
                        await send(output)
                async def run():
                    responses=[]
                    async def receive():
                        return {"type":"http.request","body":original,
                                "more_body":False}
                    async def send(message):
                        responses.append(message)
                    result=await inspect_asgi_to_disposable_journal_offline(
                        scope=scope, receive=receive, send=send,
                        trusted_fixture_keys=self.keys,
                        fixture_now_seconds=NOW,
                        fixed_test_account=ACCOUNT,
                        db_password=os.environ["PGPASSWORD"],
                    )
                    return result,responses
                with patch.object(adapter,"review_only_asgi_app",fake_asgi):
                    result,responses=asyncio.run(run())
                self.assertFalse(result.journal_recorded)
                self.assertEqual(responses[0]["status"],503)
                self.assertEqual(json.loads(responses[1]["body"])["state"],"HOLD")
                self.assertEqual(self.count("review_intents"),0)

    def test_mutated_scope_after_validation_never_records(self):
        # A caller could otherwise change headers while awaiting ASGI.
        from sender_review import ci_only_asgi_journal_handoff as adapter
        original=self.fixtures.body()
        token=self.fixtures.token("daily")
        scope={
            "type":"http","method":"POST",
            "path":"/v1/review-only/entry-intents",
            "raw_path":b"/v1/review-only/entry-intents",
            "query_string":b"",
            "headers":[
                (b"content-type", b"application/json"),
                (b"authorization", ("Bearer " + token).encode()),
                (b"content-length", str(len(original)).encode()),
            ],
        }
        async def changing_asgi(incoming_scope, receive, send):
            await receive()
            incoming_scope["headers"][0]=(b"content-type",b"application/javascript")
            hold=b'{"state":"HOLD","reason":"no authenticated sender deployed"}'
            await send({"type":"http.response.start","status":503})
            await send({"type":"http.response.body","body":hold})
        async def run():
            responses=[]
            async def receive():
                return {"type":"http.request","body":original,"more_body":False}
            async def send(message):
                responses.append(message)
            result=await inspect_asgi_to_disposable_journal_offline(
                scope=scope,receive=receive,send=send,
                trusted_fixture_keys=self.keys,fixture_now_seconds=NOW,
                fixed_test_account=ACCOUNT,db_password=os.environ["PGPASSWORD"],
            )
            return result,responses
        with patch.object(adapter,"review_only_asgi_app",changing_asgi):
            result,responses=asyncio.run(run())
        self.assertFalse(result.journal_recorded)
        self.assertEqual(responses[0]["status"],503)
        self.assertEqual(self.count("review_intents"),0)

    def test_incomplete_or_disconnected_stream_never_records_spoofed_hold(self):
        from sender_review import ci_only_asgi_journal_handoff as adapter
        body = self.fixtures.body()
        token = self.fixtures.token("daily")
        headers = [
            (b"content-type", b"application/json"),
            (b"authorization", ("Bearer " + token).encode()),
            (b"content-length", str(len(body)).encode()),
        ]
        hold = b'{"state":"HOLD","reason":"no authenticated sender deployed"}'
        cases = (
            # A positive more_body never proves the request completed.
            [{"type":"http.request","body":body,"more_body":True}],
            [{"type":"http.request","body":body[:10],"more_body":True}],
            [{"type":"http.disconnect"}],
            [{"type":"http.request","body":body,"more_body":False},
             {"type":"http.disconnect"}],
            [{"type":"http.request","body":body,"more_body":False},
             {"type":"http.request","body":b"extra","more_body":False}],
        )
        for stream in cases:
            with self.subTest(stream=stream):
                self.setUp()
                scope = {
                    "type":"http", "method":"POST",
                    "path":"/v1/review-only/entry-intents",
                    "raw_path":b"/v1/review-only/entry-intents",
                    "query_string":b"", "headers":list(headers),
                }
                async def spoofed_asgi(unused_scope, receive, send):
                    for _ in stream:
                        await receive()
                    await send({"type":"http.response.start","status":503})
                    await send({"type":"http.response.body","body":hold})
                async def run():
                    responses = []
                    remaining = iter(stream)
                    async def receive():
                        return next(remaining)
                    async def send(message):
                        responses.append(message)
                    result = await inspect_asgi_to_disposable_journal_offline(
                        scope=scope, receive=receive, send=send,
                        trusted_fixture_keys=self.keys, fixture_now_seconds=NOW,
                        fixed_test_account=ACCOUNT,
                        db_password=os.environ["PGPASSWORD"],
                    )
                    return result, responses
                with patch.object(adapter, "review_only_asgi_app", spoofed_asgi):
                    result, responses = asyncio.run(run())
                self.assertFalse(result.journal_recorded)
                self.assertEqual(responses[0]["status"], 503)
                self.assertEqual(self.count("review_intents"), 0)

    def test_spoofed_hold_with_noncanonical_http_envelope_never_records(self):
        from sender_review import ci_only_asgi_journal_handoff as adapter
        body = self.fixtures.body()
        token = self.fixtures.token("daily")
        route = "/v1/review-only/entry-intents"
        hold = b'{"state":"HOLD","reason":"no authenticated sender deployed"}'
        correct_headers = [
            (b"content-type", b"application/json"),
            (b"cache-control", b"no-store"),
            (b"content-length", str(len(hold)).encode("ascii")),
        ]
        base_scope = {
            "type":"http", "method":"POST", "path":route,
            "raw_path":route.encode(), "query_string":b"",
            "headers":[
                (b"content-type",b"application/json"),
                (b"authorization",("Bearer "+token).encode()),
                (b"content-length",str(len(body)).encode()),
            ],
        }
        variations = (
            ({}, [(b"content-type",b"text/plain"),
                  *correct_headers[1:]]),
            ({}, correct_headers[:-1] + [(b"content-length",b"999")]),
            ({}, correct_headers[:1] + correct_headers[2:]),
            ({"raw_path":b"/v1/review-only/entry-intents/"},correct_headers),
            ({"query_string":b"debug=1"},correct_headers),
            ({"headers":base_scope["headers"][:-1]+[
                (b"content-length",b"999")]},correct_headers),
            ({"headers":base_scope["headers"][:1]+[
                (b"authorization",("Bearer "+token).encode()),
                (b"content-length",b"0"+str(len(body)).encode())]},correct_headers),
        )
        for overrides, response_headers in variations:
            with self.subTest(overrides=overrides,response_headers=response_headers):
                self.setUp()
                scope = {**base_scope,**overrides}
                async def spoofed_asgi(unused_scope, receive, send):
                    await receive()
                    await send({"type":"http.response.start","status":503,
                                "headers":response_headers})
                    await send({"type":"http.response.body","body":hold})
                async def run():
                    messages = []
                    async def receive():
                        return {"type":"http.request","body":body,"more_body":False}
                    async def send(message):
                        messages.append(message)
                    result = await inspect_asgi_to_disposable_journal_offline(
                        scope=scope,receive=receive,send=send,
                        trusted_fixture_keys=self.keys,fixture_now_seconds=NOW,
                        fixed_test_account=ACCOUNT,
                        db_password=os.environ["PGPASSWORD"],
                    )
                    return result,messages
                with patch.object(adapter,"review_only_asgi_app",spoofed_asgi):
                    result,messages=asyncio.run(run())
                self.assertFalse(result.journal_recorded)
                self.assertEqual(messages[0]["status"],503)
                self.assertEqual(self.count("review_intents"),0)

    def test_disabled_ci_marker_prevents_all_database_writes(self):
        with patch.dict(os.environ, {CI_MARKER: "0"}):
            result, response=self.request()
        self.assertFalse(result.journal_recorded)
        self.assertEqual(response[0]["status"], 503)
        self.assertEqual(self.count("review_intents"), 0)


if __name__ == "__main__":
    unittest.main()
