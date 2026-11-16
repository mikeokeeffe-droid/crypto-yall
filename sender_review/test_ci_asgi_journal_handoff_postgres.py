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

    def test_disabled_ci_marker_prevents_all_database_writes(self):
        with patch.dict(os.environ, {CI_MARKER: "0"}):
            result, response=self.request()
        self.assertFalse(result.journal_recorded)
        self.assertEqual(response[0]["status"], 503)
        self.assertEqual(self.count("review_intents"), 0)


if __name__ == "__main__":
    unittest.main()
