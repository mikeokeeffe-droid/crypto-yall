"""Offline ONLY: signer-free worker draft -> fake signed identity -> CI HOLD.

Never connects to a real account, signer, remote sender or exchange.
Only disposable loopback PostgreSQL and fabricated test OIDC credentials.
"""
import hashlib
import os
import unittest

from sender_review.worker_intent_fixture_builder_offline import (
    build_worker_intent_fixture_offline,
)
from sender_review.ci_only_identity_bridge import (
    inspect_and_record_signed_fixture_offline,
)
from sender_review.test_ci_journal_postgres import (
    ACCOUNT, CI_MARKER, SQL, connect,
)
from sender_review.test_offline_oidc_identity_fixture import (
    NOW, POLICY, SignedOidcFixtureTests,
)

REF = "b" * 32


@unittest.skipUnless(
    os.environ.get(CI_MARKER) == "1"
    and os.environ.get("PGDATABASE") == "sender_review_test"
    and os.environ.get("PGHOST") == "127.0.0.1",
    "Disposable PostgreSQL CI only",
)
class WorkerDraftToJournalOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SignedOidcFixtureTests.setUpClass()
        cls.signer = SignedOidcFixtureTests()
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

    def draft(self, bot="daily", action="open_long", coin="SOL",
              nonce="a" * 32, **changes):
        fields = dict(
            fixture_bot=bot, action=action, coin=coin, side="long",
            request_nonce=nonce,
        )
        if action in ("open_long", "open_short"):
            fields.update(rounded_size="0.16", requested_leverage=2)
            if action == "open_short":
                fields["side"] = "short"
        elif action in ("pyramid_long", "pyramid_short"):
            fields.update(rounded_size="0.02", requested_leverage=2,
                          parent_position_ref=REF)
            if action == "pyramid_short":
                fields["side"] = "short"
        elif action == "protective_close":
            fields.update(close_size="0.10", observed_position_size="0.20",
                          position_ref=REF, exit_reason="profit_floor",
                          reduce_only=True)
        elif action == "request_leverage":
            fields.update(requested_leverage=2, parent_position_ref=REF)
        fields.update(changes)
        return build_worker_intent_fixture_offline(**fields)

    def review(self, token, body):
        return inspect_and_record_signed_fixture_offline(
            token=token, body=body, policy=POLICY,
            fixture_keys=self.keys, fixture_now_seconds=NOW,
            fixed_test_account=ACCOUNT, db_password=os.environ["PGPASSWORD"],
        )

    @staticmethod
    def rows(sql):
        with connect() as conn:
            return conn.execute(sql).fetchall()

    def assert_no_trading_authority(self, result):
        self.assertFalse(result.runtime_identity_authenticated)
        self.assertFalse(result.request_authorized)
        self.assertFalse(result.submit_authorized)
        self.assertFalse(result.close_authorized)

    def assert_empty_db(self):
        for table in (
            "fixture_identity_receipts", "review_intents",
            "scope_fences", "review_events", "fixture_request_evidence",
        ):
            with self.subTest(table=table):
                self.assertEqual(self.rows(
                    "SELECT count(*) FROM sender_review_ci." + table
                ), [(0,)])

    def test_all_three_worker_entries_store_exact_body_and_signed_identity_only(self):
        cases = (
            ("daily", "SOL", "a" * 32, "open_long"),
            ("intraday", "AVAX", "b" * 32, "open_short"),
            ("aggressive", "LINK", "c" * 32, "open_long"),
        )
        for bot, coin, nonce, action in cases:
            with self.subTest(bot=bot):
                draft = self.draft(bot=bot, coin=coin, nonce=nonce, action=action)
                self.assertEqual(draft.state, "fixture_body_review_only_HOLD")
                self.assertFalse(draft.submit_authorized)
                token = self.signer.token(bot=bot, jti="worker-review-" + bot)
                result = self.review(token, draft.fixture_body)
                self.assertEqual(result.state, "persisted_fixture_review_only_HOLD")
                self.assertEqual(result.fixture_bot, bot)
                self.assertTrue(result.fixture_signature_checked)
                self.assertTrue(result.journal_recorded)
                self.assert_no_trading_authority(result)
                self.assertEqual(self.rows(
                    "SELECT e.bot,i.coin,e.jti,e.body_sha256,e.token_sha256 "
                    "FROM sender_review_ci.fixture_request_evidence e "
                    "JOIN sender_review_ci.review_intents i ON i.id=e.intent_id "
                    "WHERE e.request_nonce='" + nonce + "'"
                ), [(
                    bot, coin, "worker-review-" + bot,
                    hashlib.sha256(draft.fixture_body).hexdigest(),
                    hashlib.sha256(token.encode("ascii")).hexdigest(),
                )])
        self.assertEqual(self.rows(
            "SELECT count(*) FROM sender_review_ci.review_events"
        ), [(3,)])
        self.assertEqual(self.rows(
            "SELECT DISTINCT state FROM sender_review_ci.review_intents"
        ), [("review_only",)])

    def test_pyramid_protective_close_and_leverage_cannot_enter_entry_journal(self):
        cases = (
            ("aggressive", "pyramid_long"),
            ("aggressive", "pyramid_short"),
            ("daily", "protective_close"),
            ("intraday", "protective_close"),
            ("aggressive", "protective_close"),
            ("daily", "request_leverage"),
        )
        for bot, action in cases:
            with self.subTest(bot=bot, action=action):
                draft = self.draft(bot=bot, action=action)
                self.assertEqual(draft.state, "fixture_body_review_only_HOLD")
                token = self.signer.token(
                    bot=bot, jti="nonentry-" + bot + "-" + action
                )
                result = self.review(token, draft.fixture_body)
                self.assertEqual(result.state, "hold")
                self.assertEqual(result.reason, "invalid or non-entry request")
                self.assertFalse(result.journal_recorded)
                self.assert_no_trading_authority(result)
                self.assert_empty_db()

    def test_replay_and_authority_injection_fail_without_new_journal_evidence(self):
        draft = self.draft(bot="daily")
        token = self.signer.token(bot="daily", jti="worker-replay-fixture")
        self.assertTrue(self.review(token, draft.fixture_body).journal_recorded)
        prior = self.rows(
            "SELECT body_sha256,token_sha256 FROM "
            "sender_review_ci.fixture_request_evidence"
        )
        self.assertEqual(self.review(token, draft.fixture_body).state, "hold")
        for forbidden in (
            b',"bot":"aggressive"',
            b',"submit_authorized":true',
            b',"account":"0x2222222222222222222222222222222222222222"',
        ):
            with self.subTest(forbidden=forbidden):
                # The entry contract rejects caller authority fields before
                # the database, even when presented with a signed fixture.
                tampered = draft.fixture_body[:-1] + forbidden + b"}"
                denied = self.review(
                    self.signer.token(bot="intraday",
                                      jti="new-authority-fixture"), tampered
                )
                self.assertEqual(denied.state, "hold")
                self.assert_no_trading_authority(denied)
        self.assertEqual(self.rows(
            "SELECT body_sha256,token_sha256 FROM "
            "sender_review_ci.fixture_request_evidence"
        ), prior)
        self.assertEqual(self.rows(
            "SELECT count(*) FROM sender_review_ci.fixture_identity_receipts"
        ), [(1,)])


if __name__ == "__main__":
    unittest.main()
