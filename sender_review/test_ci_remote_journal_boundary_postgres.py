"""CI-only fake HTTP/OIDC request through atomic disposable journal HOLD."""
import hashlib
import os
import unittest

from sender_review.ci_only_remote_journal_boundary import (
    review_remote_fixture_to_disposable_journal_offline,
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
    "Disposable PostgreSQL CI only",
)
class FakeRemoteJournalBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OfflineRemoteRequestBoundaryTests.setUpClass()
        cls.fixture = OfflineRemoteRequestBoundaryTests()
        cls.keys = OfflineRemoteRequestBoundaryTests.keys
        with connect() as conn:
            conn.execute(SQL.read_text(encoding="utf-8"))

    def setUp(self):
        with connect() as conn:
            conn.execute(
                "TRUNCATE sender_review_ci.fixture_identity_receipts,"
                "sender_review_ci.review_events,"
                "sender_review_ci.review_intents,"
                "sender_review_ci.scope_fences RESTART IDENTITY CASCADE"
            )

    @staticmethod
    def rows(sql):
        with connect() as conn:
            return conn.execute(sql).fetchall()

    def send(self, *, token=None, body=None, headers=None,
             method="POST", path="/v1/review-only/entry-intents"):
        if token is None:
            token = self.fixture.token("daily")
        if body is None:
            body = self.fixture.body()
        if headers is None:
            headers = [
                ("Authorization", "Bearer " + token),
                ("Content-Type", "application/json"),
            ]
        return review_remote_fixture_to_disposable_journal_offline(
            method=method, path=path, headers=headers, body=body,
            trusted_fixture_keys=self.keys, fixture_now_seconds=NOW,
            fixed_test_account=ACCOUNT, db_password=os.environ["PGPASSWORD"],
        )

    def assert_no_authority(self, result):
        for name in (
            "runtime_identity_authenticated", "tls_peer_authenticated",
            "request_authorized", "submit_authorized", "close_authorized",
            "leverage_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, name), False)

    def assert_empty(self):
        for table in (
            "fixture_identity_receipts", "scope_fences",
            "review_intents", "review_events", "fixture_request_evidence",
        ):
            with self.subTest(table=table):
                self.assertEqual(self.rows(
                    "SELECT count(*) FROM sender_review_ci." + table
                ), [(0,)])

    def test_three_signed_http_fixtures_record_exact_request_without_authority(self):
        for bot, coin, nonce in (
            ("daily", "SOL", "a" * 32),
            ("intraday", "AVAX", "b" * 32),
            ("aggressive", "LINK", "c" * 32),
        ):
            with self.subTest(bot=bot):
                token = self.fixture.token(bot, jti="remote-fixture-" + bot)
                body = self.fixture.body(coin=coin, request_nonce=nonce)
                outcome = self.send(token=token, body=body)
                self.assertEqual(
                    outcome.state, "persisted_remote_fixture_review_only_HOLD"
                )
                self.assertEqual(outcome.fixture_bot, bot)
                self.assertTrue(outcome.journal_recorded)
                self.assert_no_authority(outcome)
                self.assertEqual(
                    outcome.request_sha256, hashlib.sha256(body).hexdigest()
                )
                self.assertEqual(self.rows(
                    "SELECT e.body_sha256,e.token_sha256,e.bot,i.coin "
                    "FROM sender_review_ci.fixture_request_evidence e "
                    "JOIN sender_review_ci.review_intents i ON i.id=e.intent_id "
                    "WHERE e.request_nonce='" + nonce + "'"
                ), [(
                    hashlib.sha256(body).hexdigest(),
                    hashlib.sha256(token.encode("ascii")).hexdigest(),
                    bot, coin,
                )])
        self.assertEqual(self.rows(
            "SELECT count(*) FROM sender_review_ci.review_intents"
        ), [(3,)])
        self.assertEqual(self.rows(
            "SELECT distinct state FROM sender_review_ci.review_intents"
        ), [("review_only",)])

    def test_invalid_envelopes_signatures_and_actions_leave_db_empty(self):
        good_token = self.fixture.token("daily")
        good_body = self.fixture.body()
        cases = (
            dict(method="GET"),
            dict(path="/v1/trade"),
            dict(headers=[
                ("Authorization", "Bearer " + good_token),
                ("authorization", "Bearer " + good_token),
            ]),
            dict(headers=[
                ("Authorization", "Bearer " + good_token),
                ("Content-Type", "application/json"),
                ("X-Trusted-Bot", "aggressive"),
            ]),
            dict(token=self.fixture.token("daily", repository_id="other")),
            dict(token=self.fixture.token("daily", run_attempt="2", event_name="pull_request_target")),
            dict(body=self.fixture.body(bot="aggressive")),
            dict(body=self.fixture.body(action="protective_close")),
            dict(body=self.fixture.body(account="0x" + "2" * 40)),
        )
        for case in cases:
            with self.subTest(case=case):
                result = self.send(**case)
                self.assertEqual(result.state, "hold")
                self.assertFalse(result.journal_recorded)
                self.assert_no_authority(result)
                self.assert_empty()

    def test_wrong_signed_workflow_run_cannot_create_any_database_rows(self):
        # The outer fake HTTP boundary checks the pinned CI fixture
        # run/attempt BEFORE a DB transaction can consume a JTI.
        for changes in (
            {"run_id": "123456788"},
            {"run_id": "123456790"},
            {"run_attempt": "2"},
            {"run_attempt": "3"},
            {"run_attempt": "01"},
        ):
            with self.subTest(changes=changes):
                signed = self.fixture.token("daily", **changes)
                result = self.send(token=signed)
                self.assertEqual(result.state, "hold")
                self.assertFalse(result.journal_recorded)
                self.assert_no_authority(result)
                self.assert_empty()
        accepted = self.send(token=self.fixture.token("daily"))
        self.assertTrue(accepted.journal_recorded)
        self.assert_no_authority(accepted)
        self.assertEqual(self.rows(
            "SELECT count(*) FROM sender_review_ci.fixture_identity_receipts"
        ), [(1,)])

    def test_replay_and_cross_coin_collision_leave_no_extra_evidence(self):
        token = self.fixture.token("intraday", jti="remote-replay-identity")
        body = self.fixture.body(coin="AVAX", request_nonce="d" * 32)
        first = self.send(token=token, body=body)
        self.assertTrue(first.journal_recorded)
        for candidate_token, candidate_body in (
            (token, body),
            (token, self.fixture.body(coin="LINK", request_nonce="e" * 32)),
            (self.fixture.token("aggressive", jti="remote-new-identity"),
             self.fixture.body(coin="LINK", request_nonce="d" * 32)),
        ):
            denied = self.send(token=candidate_token, body=candidate_body)
            self.assertEqual(denied.state, "hold")
            self.assert_no_authority(denied)
        self.assertEqual(self.rows(
            "SELECT count(*) FROM sender_review_ci.fixture_identity_receipts"
        ), [(1,)])
        self.assertEqual(self.rows(
            "SELECT count(*) FROM sender_review_ci.fixture_request_evidence"
        ), [(1,)])
        self.assertEqual(self.rows(
            "SELECT coin,fence,active_nonce FROM sender_review_ci.scope_fences"
        ), [("AVAX", 1, "d" * 32)])


if __name__ == "__main__":
    unittest.main()
