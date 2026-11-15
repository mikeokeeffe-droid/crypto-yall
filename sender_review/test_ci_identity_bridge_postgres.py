"""Disposable-only integration: signed fixture, nonce receipt, journal HOLD."""
import concurrent.futures
import json
import os
import unittest

from sender_review.ci_only_identity_bridge import (
    inspect_and_record_signed_fixture_offline,
)
from sender_review.test_ci_journal_postgres import (
    ACCOUNT, CI_MARKER, SQL, connect,
)
from sender_review.test_offline_oidc_identity_fixture import (
    NOW, POLICY, SignedOidcFixtureTests,
)


@unittest.skipUnless(
    os.environ.get(CI_MARKER) == "1"
    and os.environ.get("PGDATABASE") == "sender_review_test"
    and os.environ.get("PGHOST") == "127.0.0.1",
    "Disposable local PostgreSQL CI is required",
)
class SignedIdentityBridgePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SignedOidcFixtureTests.setUpClass()
        cls.fixture = SignedOidcFixtureTests()
        cls.keys = SignedOidcFixtureTests.keys
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
    def body(nonce="a" * 32, **changes):
        data = {
            "version": 1, "action": "open_long", "side": "long",
            "coin": "SOL", "rounded_size": "0.16",
            "requested_leverage": 2, "request_nonce": nonce,
        }
        data.update(changes)
        return json.dumps(data).encode()

    def submit(self, *, bot="daily", token=None, body=None, **kwargs):
        if token is None:
            token = self.fixture.token(bot=bot)
        if body is None:
            body = self.body()
        return inspect_and_record_signed_fixture_offline(
            token=token, body=body, policy=POLICY,
            fixture_keys=self.keys, fixture_now_seconds=NOW,
            fixed_test_account=ACCOUNT, db_password=os.environ["PGPASSWORD"],
            **kwargs,
        )

    def rows(self, sql):
        with connect() as conn:
            return conn.execute(sql).fetchall()

    def test_signed_workflow_identity_is_server_derived_and_non_authorizing(self):
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                self.setUp()
                r = self.submit(bot=bot)
                self.assertEqual(r.state, "persisted_fixture_review_only_HOLD")
                self.assertEqual(r.fixture_bot, bot)
                self.assertTrue(r.fixture_signature_checked)
                self.assertTrue(r.journal_recorded)
                self.assertFalse(r.runtime_identity_authenticated)
                self.assertFalse(r.request_authorized)
                self.assertFalse(r.submit_authorized)
                self.assertFalse(r.close_authorized)
                self.assertEqual(
                    self.rows("select bot from sender_review_ci.review_intents"),
                    [(bot,)],
                )

    def test_replay_denied_across_fresh_database_connections(self):
        token = self.fixture.token("daily")
        self.assertTrue(self.submit(token=token).journal_recorded)
        self.assertEqual(self.submit(token=token).state, "hold")
        self.assertEqual(self.submit(token=token, body=self.body("b"*32)).state, "hold")
        self.assertEqual(len(self.rows(
            "select 1 from sender_review_ci.fixture_identity_receipts"
        )), 1)
        self.assertEqual(len(self.rows(
            "select 1 from sender_review_ci.review_intents"
        )), 1)

    def test_bad_signature_expiry_and_claims_do_not_touch_database(self):
        token = self.fixture.token("daily")
        cases = (
            token[:-2] + "xx",
            self.fixture.token("daily", exp=NOW),
            self.fixture.token("daily", repository_id="attacker"),
            self.fixture.token("daily", event_name="pull_request_target"),
        )
        for bad in cases:
            with self.subTest(bad=bad[-12:]):
                self.assertEqual(self.submit(token=bad).state, "hold")
        self.assertEqual(self.rows(
            "select 1 from sender_review_ci.fixture_identity_receipts"
        ), [])

    def test_caller_bot_account_and_non_entry_actions_cannot_grant_authority(self):
        for body in (
            self.body(bot="aggressive"),
            self.body(account="0x"+"2"*40),
            self.body(submit_authorized=True),
            self.body(action="close", side="long"),
        ):
            with self.subTest(body=body):
                self.assertEqual(self.submit(body=body).state, "hold")
        self.assertEqual(self.rows(
            "select 1 from sender_review_ci.review_intents"
        ), [])

    def test_same_coin_three_bots_compete_only_one_fixture_review_recorded(self):
        jobs = (
            ("daily", "a"*32),
            ("intraday", "b"*32),
            ("aggressive", "c"*32),
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [
                pool.submit(self.submit, token=self.fixture.token(bot),
                            body=self.body(nonce))
                for bot, nonce in jobs
            ]
            results = [f.result(timeout=10) for f in futures]
        self.assertEqual(sum(x.journal_recorded for x in results), 1)
        self.assertEqual(len(self.rows(
            "select 1 from sender_review_ci.fixture_identity_receipts"
        )), 1)
        self.assertEqual(len(self.rows(
            "select 1 from sender_review_ci.review_intents"
        )), 1)

    def test_same_signed_token_different_coins_never_crosses_scope(self):
        token = self.fixture.token("daily")
        self.assertTrue(self.submit(token=token).journal_recorded)
        denied = self.submit(token=token, body=self.body("b"*32, coin="AVAX"))
        self.assertEqual(denied.state, "hold")
        self.assertEqual(len(self.rows(
            "select 1 from sender_review_ci.review_intents"
        )), 1)

    def test_journal_hold_rolls_back_second_fixture_receipt(self):
        first = self.submit(token=self.fixture.token("daily"),
                            body=self.body("a"*32))
        self.assertTrue(first.journal_recorded)
        denied = self.submit(token=self.fixture.token("intraday", jti="jti-002"),
                             body=self.body("b"*32))
        self.assertEqual(denied.state, "hold")
        self.assertIn("journal-denied", denied.reason)
        self.assertEqual(len(self.rows(
            "select 1 from sender_review_ci.fixture_identity_receipts"
        )), 1)

    def test_disabled_ci_marker_never_connects_or_records(self):
        old = os.environ.pop(CI_MARKER, None)
        try:
            r = self.submit()
        finally:
            if old is not None:
                os.environ[CI_MARKER] = old
        self.assertEqual(r.state, "hold")
        self.assertEqual(self.rows(
            "select 1 from sender_review_ci.fixture_identity_receipts"
        ), [])


if __name__ == "__main__":
    unittest.main()
