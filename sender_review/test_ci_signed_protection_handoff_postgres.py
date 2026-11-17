"""CI-only HTTP signed-fixture -> request evidence -> durable HOLD proof."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from sender_review.ci_only_signed_protection_handoff import (
    record_signed_protection_fixture_offline,
)
from sender_review.test_ci_journal_postgres import (
    ACCOUNT, CI_MARKER, SQL, connect,
)
from sender_review.test_remote_request_boundary_offline import (
    NOW, OfflineRemoteRequestBoundaryTests,
)

HOLD_SQL = Path(__file__).with_name("ci_only_protection_reentry_holds.sql")


@unittest.skipUnless(
    os.environ.get(CI_MARKER) == "1"
    and os.environ.get("PGDATABASE") == "sender_review_test"
    and os.environ.get("PGHOST") == "127.0.0.1",
    "Local disposable PostgreSQL CI only",
)
class SignedProtectionHandoffPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OfflineRemoteRequestBoundaryTests.setUpClass()
        cls.fixture = OfflineRemoteRequestBoundaryTests()
        cls.keys = OfflineRemoteRequestBoundaryTests.keys
        with connect() as db:
            db.execute(SQL.read_text("utf-8"))
            db.execute(HOLD_SQL.read_text("utf-8"))

    def setUp(self):
        with connect() as db:
            db.execute(
                "TRUNCATE sender_review_ci.fixture_identity_receipts,"
                "sender_review_ci.review_events,"
                "sender_review_ci.review_intents,"
                "sender_review_ci.scope_fences RESTART IDENTITY CASCADE"
            )

    @staticmethod
    def rows(sql):
        with connect() as db:
            return db.execute(sql).fetchall()

    def send(self, bot="daily", coin="SOL", nonce="a"*32,
             outcome="unknown_ack", **changes):
        token = self.fixture.token(bot, jti="handoff-"+bot+"-"+coin)
        body = self.fixture.body(coin=coin, request_nonce=nonce)
        args = dict(
            method="POST", path="/v1/review-only/entry-intents",
            headers=[("Authorization", "Bearer "+token),
                     ("Content-Type", "application/json")],
            body=body, trusted_fixture_keys=self.keys,
            fixture_now_seconds=NOW, fixed_test_account=ACCOUNT,
            db_password=os.environ["PGPASSWORD"], outcome_fixture=outcome,
        )
        args.update(changes)
        return record_signed_protection_fixture_offline(**args)

    def deny_authority(self, outcome):
        for key in (
            "runtime_identity_authenticated", "real_exchange_outcome_verified",
            "position_ownership_verified", "protective_exit_confirmed",
            "lock_released", "retry_authorized", "submit_authorized",
            "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(outcome, key), False, key)

    def test_all_three_signed_workflow_fixtures_produce_permanent_holds(self):
        for bot, coin, nonce, label in (
            ("daily", "SOL", "a"*32, "unknown_ack"),
            ("intraday", "AVAX", "b"*32, "partial_fill"),
            ("aggressive", "LINK", "c"*32, "claimed_closed"),
        ):
            with self.subTest(bot=bot):
                response = self.send(bot, coin, nonce, label)
                self.assertEqual(response.state,
                                 "PERSISTED_FAKE_PROTECTION_HOLD_NO_GO")
                self.assertTrue(response.journal_recorded)
                self.assertTrue(response.simulated_protection_hold_recorded)
                self.assertEqual(response.persisted_scope_fence, 1)
                self.deny_authority(response)
        self.assertEqual(self.rows(
            "SELECT bot,coin,outcome_fixture FROM "
            "sender_review_ci.simulated_protection_reentry_holds ORDER BY coin"
        ), [
            ("intraday", "AVAX", "partial_fill"),
            ("aggressive", "LINK", "claimed_closed"),
            ("daily", "SOL", "unknown_ack"),
        ])
        self.assertEqual(self.rows(
            "SELECT count(*) FROM sender_review_ci.fixture_request_evidence"
        ), [(3,)])
        self.assertEqual(self.rows(
            "SELECT bool_and(fence_still_held),count(*) FROM "
            "sender_review_ci.simulated_protection_hold_review"
        ), [(True,3)])

    def test_replay_cross_bot_and_same_coin_are_blocked(self):
        self.assertTrue(self.send().simulated_protection_hold_recorded)
        for response in (
            self.send(),
            self.send(bot="intraday", coin="SOL", nonce="b"*32),
            self.send(bot="aggressive", coin="SOL", nonce="c"*32),
            self.send(bot="daily", coin="AVAX", nonce="a"*32),
        ):
            self.assertEqual(response.state, "HOLD")
            self.assertFalse(response.journal_recorded)
            self.deny_authority(response)
        self.assertEqual(self.rows(
            "SELECT count(*) FROM sender_review_ci.simulated_protection_reentry_holds"
        ), [(1,)])

    def test_invalid_identity_and_request_create_no_rows(self):
        for changes in (
            {"method": "GET"},
            {"path": "/exchange"},
            {"trusted_fixture_keys": {}},
            {"fixed_test_account": "0x"+"2"*40},
            {"outcome_fixture": "trade_confirmed"},
            {"body": self.fixture.body(action="protective_close")},
            {"headers": [("Authorization", "Bearer fake"),
                         ("Content-Type", "application/json")]},
        ):
            with self.subTest(change=str(changes)[:70]):
                result = self.send(**changes)
                self.assertFalse(result.journal_recorded)
                self.assertFalse(result.simulated_protection_hold_recorded)
                self.deny_authority(result)
                self.assertEqual(self.rows(
                    "SELECT count(*) FROM sender_review_ci.review_intents"
                ), [(0,)])
        with patch.dict(os.environ, {CI_MARKER: "0"}):
            result = self.send()
        self.assertFalse(result.journal_recorded)
        self.deny_authority(result)

    def test_audit_detects_missing_second_stage_and_retained_fence(self):
        # A signed fake request recorded WITHOUT the optional second stage
        # remains an unresolved protected-handoff review; no auto recovery.
        from sender_review.ci_only_remote_journal_boundary import (
            review_remote_fixture_to_disposable_journal_offline,
        )
        token = self.fixture.token("daily", jti="audit-missing-hold")
        body = self.fixture.body(coin="SOL", request_nonce="d"*32)
        result = review_remote_fixture_to_disposable_journal_offline(
            method="POST", path="/v1/review-only/entry-intents",
            headers=[("Authorization", "Bearer "+token),
                     ("Content-Type", "application/json")],
            body=body, trusted_fixture_keys=self.keys,
            fixture_now_seconds=NOW, fixed_test_account=ACCOUNT,
            db_password=os.environ["PGPASSWORD"],
        )
        self.assertTrue(result.journal_recorded)
        audit = self.rows(
            "SELECT protection_hold_recorded,fence_still_held,review_state "
            "FROM sender_review_ci.simulated_protection_handoff_audit"
        )
        self.assertEqual(audit, [(
            False, True, "CRITICAL_SIGNED_FIXTURE_WITHOUT_PROTECTION_HOLD"
        )])
        from sender_review.test_ci_journal_postgres import record
        self.assertFalse(record(bot="aggressive", coin="SOL",
                                nonce="e"*32)[0])

    def test_audit_links_recorded_hold_and_flags_fence_tampering(self):
        result = self.send()
        self.assertTrue(result.simulated_protection_hold_recorded)
        query = (
            "SELECT bot,coin,protection_hold_recorded,fence_still_held,"
            "review_state FROM sender_review_ci."
            "simulated_protection_handoff_audit"
        )
        self.assertEqual(self.rows(query), [(
            "daily", "SOL", True, True,
            "PERSISTED_FIXTURE_HOLD_NO_REAL_PROTECTION"
        )])
        with connect() as db:
            db.execute(
                "UPDATE sender_review_ci.scope_fences SET active_nonce=NULL "
                "WHERE coin='SOL'"
            )
        self.assertEqual(self.rows(query), [(
            "daily", "SOL", True, False,
            "CRITICAL_FENCE_MISSING_OR_CHANGED"
        )])

    def test_audit_read_access_is_not_public(self):
        with connect() as db:
            self.assertFalse(db.execute(
                "SELECT has_table_privilege('public', "
                "'sender_review_ci.simulated_protection_handoff_audit', "
                "'SELECT')"
            ).fetchone()[0])
            self.assertTrue(db.execute(
                "SELECT reloptions FROM pg_class "
                "WHERE oid='sender_review_ci.simulated_protection_handoff_audit'"
                "::regclass"
            ).fetchone()[0] == ["security_invoker=true"])

    def test_after_first_commit_missing_second_stage_stays_fenced(self):
        # The signing-fixture bridge can commit first; if the new table was
        # never installed or the second transaction fails, the first fence
        # remains, so a different bot cannot enter the same account/coin.
        with connect() as db:
            db.execute("ALTER TABLE sender_review_ci.simulated_protection_reentry_holds "
                       "RENAME TO simulated_protection_reentry_holds_unavailable")
        try:
            response = self.send()
            self.assertTrue(response.journal_recorded)
            self.assertFalse(response.simulated_protection_hold_recorded)
            self.deny_authority(response)
            self.assertEqual(self.rows(
                "SELECT active_nonce FROM sender_review_ci.scope_fences"
            ), [("a"*32,)])
            from sender_review.test_ci_journal_postgres import record
            self.assertFalse(record(bot="aggressive", coin="SOL",
                                    nonce="b"*32)[0])
        finally:
            with connect() as db:
                db.execute("ALTER TABLE "
                           "sender_review_ci.simulated_protection_reentry_holds_unavailable "
                           "RENAME TO simulated_protection_reentry_holds")

if __name__ == "__main__":
    unittest.main()
