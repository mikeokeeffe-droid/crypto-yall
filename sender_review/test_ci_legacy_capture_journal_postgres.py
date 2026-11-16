"""Three ORIGINAL executor sizing functions -> disposable signed HOLD journal.

This is a CI-only integration test: no original executor is imported or changed.
Its single execute_trade function is extracted as syntax, and its exchange is
a fake that can NEVER sign, open, close, or set real leverage. The journal
is a disposable local sender_review_test PostgreSQL instance only.
No result, even a persisted record, authorizes an actual order.
"""
import hashlib
import json
import os
import unittest
from unittest.mock import patch

from sender_review.legacy_order_capture_preview import (
    LegacyOrderCapturePreview, ReviewOnlyMutationBlocked,
)
from sender_review.test_legacy_order_capture_preview import (
    FILES, isolated_legacy_execute_trade,
)
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
class LegacySizingToDisposableJournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OfflineRemoteRequestBoundaryTests.setUpClass()
        cls.fixture = OfflineRemoteRequestBoundaryTests()
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

    def rows(self, statement):
        with connect() as db:
            return db.execute(statement).fetchall()

    def capture(self, *, bot, coin, action, nonce):
        # Explicit action metadata is mandatory; never convert pyramids
        # or closes into a generic market_open intent.
        fake_exchange = LegacyOrderCapturePreview(
            fixture_bot=bot, fixture_nonce=nonce, expected_action=action,
        )
        run_unchanged_sizing = isolated_legacy_execute_trade(FILES[bot])
        with patch.dict(os.environ, {"HL_TESTNET": "false"}, clear=True):
            result = run_unchanged_sizing(
                None, fake_exchange,
                {"hl_coin": coin, "action": action},
                1000, 2,
            )
        self.assertEqual(result["status"], "NO_SEND_REVIEW_ONLY")
        self.assertEqual(result["exchange_response"]["status"], "error")
        self.assertEqual(fake_exchange.calls, [
            "reviewed_leverage_only", "entry_proposal_only",
        ])
        self.assertFalse(fake_exchange.signing_enabled)
        self.assertFalse(fake_exchange.submit_authorized)
        self.assertFalse(fake_exchange.close_authorized)
        return fake_exchange.proposed_body

    def journal(self, *, bot, nonce, body, jti=None):
        token = self.fixture.token(
            bot, jti=jti or ("legacy-capture-" + bot),
        )
        result = review_remote_fixture_to_disposable_journal_offline(
            method="POST",
            path="/v1/review-only/entry-intents",
            headers=[
                ("Authorization", "Bearer " + token),
                ("Content-Type", "application/json"),
            ],
            body=body,
            trusted_fixture_keys=self.keys,
            fixture_now_seconds=NOW,
            fixed_test_account=ACCOUNT,
            db_password=os.environ["PGPASSWORD"],
        )
        self.assertFalse(result.runtime_identity_authenticated)
        self.assertFalse(result.tls_peer_authenticated)
        self.assertFalse(result.submit_authorized)
        self.assertFalse(result.close_authorized)
        self.assertFalse(result.signing_enabled)
        return result, token

    def test_three_existing_bots_capture_and_record_exact_request_bytes(self):
        for bot, coin, nonce in (
            ("daily", "SOL", "a" * 32),
            ("intraday", "AVAX", "b" * 32),
            ("aggressive", "LINK", "c" * 32),
        ):
            for action in ("open_long", "open_short"):
                with self.subTest(bot=bot, action=action):
                    # Use a fresh disposable scope for each direction.
                    with connect() as db:
                        db.execute(
                            "TRUNCATE sender_review_ci.fixture_identity_receipts,"
                            "sender_review_ci.review_events,"
                            "sender_review_ci.review_intents,"
                            "sender_review_ci.scope_fences RESTART IDENTITY CASCADE"
                        )
                    body = self.capture(
                        bot=bot, coin=coin, action=action, nonce=nonce,
                    )
                    proposal = json.loads(body)
                    self.assertEqual(proposal["action"], action)
                    self.assertEqual(proposal["rounded_size"], "2.0")
                    self.assertEqual(proposal["requested_leverage"], 2)
                    result, token = self.journal(
                        bot=bot, nonce=nonce, body=body,
                    )
                    self.assertEqual(
                        result.state, "persisted_remote_fixture_review_only_HOLD"
                    )
                    self.assertTrue(result.journal_recorded)
                    self.assertEqual(result.fixture_bot, bot)
                    self.assertEqual(
                        result.request_sha256, hashlib.sha256(body).hexdigest()
                    )
                    self.assertEqual(self.rows(
                        "SELECT e.body_sha256,e.token_sha256,e.bot,"
                        "i.coin,i.action,i.state FROM "
                        "sender_review_ci.fixture_request_evidence e "
                        "JOIN sender_review_ci.review_intents i "
                        "ON i.id=e.intent_id"
                    ), [(
                        hashlib.sha256(body).hexdigest(),
                        hashlib.sha256(token.encode("ascii")).hexdigest(),
                        bot, coin, action, "review_only",
                    )])
                    self.assertEqual(self.rows(
                        "SELECT coin,active_nonce FROM "
                        "sender_review_ci.scope_fences"
                    ), [(coin, nonce)])

    def test_competing_bots_same_coin_cannot_record_second_entry(self):
        first_body = self.capture(
            bot="daily", coin="SOL", action="open_long", nonce="a" * 32,
        )
        first, _ = self.journal(
            bot="daily", nonce="a" * 32, body=first_body,
            jti="legacy-competing-daily",
        )
        self.assertTrue(first.journal_recorded)
        second_body = self.capture(
            bot="intraday", coin="SOL", action="open_short",
            nonce="b" * 32,
        )
        second, _ = self.journal(
            bot="intraday", nonce="b" * 32, body=second_body,
            jti="legacy-competing-intraday",
        )
        self.assertEqual(second.state, "hold")
        self.assertFalse(second.journal_recorded)
        self.assertEqual(self.rows(
            "SELECT bot,coin,request_nonce,state "
            "FROM sender_review_ci.review_intents"
        ), [("daily", "SOL", "a" * 32, "review_only")])
        self.assertEqual(self.rows(
            "SELECT COUNT(*) FROM sender_review_ci.fixture_identity_receipts"
        ), [(1,)])
        self.assertEqual(self.rows(
            "SELECT COUNT(*) FROM sender_review_ci.fixture_request_evidence"
        ), [(1,)])

    def test_replay_of_original_captured_entry_does_not_duplicate(self):
        body = self.capture(
            bot="aggressive", coin="LINK", action="open_long",
            nonce="d" * 32,
        )
        first, _ = self.journal(
            bot="aggressive", nonce="d" * 32, body=body,
            jti="legacy-replay-aggressive",
        )
        second, _ = self.journal(
            bot="aggressive", nonce="d" * 32, body=body,
            jti="legacy-replay-aggressive",
        )
        self.assertTrue(first.journal_recorded)
        self.assertEqual(second.state, "hold")
        self.assertFalse(second.journal_recorded)
        self.assertEqual(self.rows(
            "SELECT COUNT(*) FROM sender_review_ci.review_intents"
        ), [(1,)])

    def test_closes_and_pyramids_cannot_reach_disposable_journal(self):
        for bot in FILES:
            for action in ("close", "pyramid_long", "pyramid_short"):
                with self.subTest(bot=bot, action=action):
                    with self.assertRaises(ValueError):
                        self.capture(
                            bot=bot, coin="SOL", action=action,
                            nonce="f" * 32,
                        )
        preview = LegacyOrderCapturePreview(
            fixture_bot="intraday", fixture_nonce="e" * 32,
            expected_action="open_long",
        )
        with self.assertRaises(ReviewOnlyMutationBlocked):
            preview.market_close("SOL", sz=1.0)
        self.assertEqual(self.rows(
            "SELECT COUNT(*) FROM sender_review_ci.review_intents"
        ), [(0,)])


if __name__ == "__main__":
    unittest.main()
