"""Disposable PostgreSQL test-only simulated attempt lifecycle; NO orders."""
import concurrent.futures
import os
from pathlib import Path
import unittest

import psycopg

from sender_review.ci_only_identity_bridge import (
    inspect_and_record_signed_fixture_offline,
)
from sender_review.test_ci_journal_postgres import (
    ACCOUNT, CI_MARKER, SQL, connect,
)
from sender_review.test_offline_oidc_identity_fixture import (
    NOW, POLICY, SignedOidcFixtureTests,
)

SCRIPT = Path(__file__).with_name("ci_only_attempt_lifecycle.sql")


@unittest.skipUnless(
    os.environ.get(CI_MARKER) == "1"
    and os.environ.get("PGDATABASE") == "sender_review_test"
    and os.environ.get("PGHOST") == "127.0.0.1",
    "Only disposable local PostgreSQL CI is allowed",
)
class SimulatedAttemptLifecyclePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SignedOidcFixtureTests.setUpClass()
        cls.fixture = SignedOidcFixtureTests()
        cls.keys = SignedOidcFixtureTests.keys
        with connect() as conn:
            conn.execute(SQL.read_text(encoding="utf-8"))
            conn.execute(SCRIPT.read_text(encoding="utf-8"))

    def setUp(self):
        with connect() as conn:
            conn.execute(
                "TRUNCATE sender_review_ci.simulated_attempt_events,"
                "sender_review_ci.fixture_identity_receipts,"
                "sender_review_ci.review_events,"
                "sender_review_ci.review_intents,"
                "sender_review_ci.scope_fences RESTART IDENTITY CASCADE"
            )

    def query(self, sql, args=()):
        with connect() as conn:
            return conn.execute(sql, args).fetchall()

    def seed(self, bot="daily", coin="SOL", nonce="a" * 32):
        body = (
            b'{"version":1,"action":"open_long","side":"long",'
            b'"coin":"' + coin.encode("ascii") +
            b'","rounded_size":"0.16","requested_leverage":2,'
            b'"request_nonce":"' + nonce.encode("ascii") + b'"}'
        )
        result = inspect_and_record_signed_fixture_offline(
            token=self.fixture.token(bot, jti="attempt-" + bot + "-" + coin),
            body=body, policy=POLICY, fixture_keys=self.keys,
            fixture_now_seconds=NOW, fixed_test_account=ACCOUNT,
            db_password=os.environ["PGPASSWORD"],
        )
        self.assertTrue(result.journal_recorded)
        self.assertFalse(result.submit_authorized)
        return result.assigned_fence

    def start(self, coin="SOL", nonce="a" * 32, fence=1, account=ACCOUNT):
        return self.query(
            "SELECT recorded,reason FROM "
            "sender_review_ci.record_simulated_attempt_start(%s,%s,%s,%s)",
            (account, coin, nonce, fence),
        )[0]

    def hold(self, coin="SOL", nonce="a" * 32, fence=1, account=ACCOUNT):
        return self.query(
            "SELECT held,reason FROM "
            "sender_review_ci.hold_simulated_attempt_unknown(%s,%s,%s,%s)",
            (account, coin, nonce, fence),
        )[0]

    def test_signed_evidence_required_and_start_is_single_use(self):
        self.assertEqual(self.start(), (False, "unverified-or-unheld-review-intent"))
        self.assertEqual(self.hold(), (False, "no-started-review-attempt"))
        self.assertEqual(self.seed(), 1)
        self.assertEqual(self.start(), (True, "simulated-start-recorded-no-send"))
        self.assertEqual(
            self.start(), (False, "simulated-attempt-already-recorded")
        )
        self.assertEqual(self.query(
            "SELECT kind FROM sender_review_ci.simulated_attempt_events"
        ), [("simulated_attempt_started",)])
        self.assertEqual(self.query(
            "SELECT state FROM sender_review_ci.review_intents"
        ), [("review_only",)])
        self.assertEqual(self.query(
            "SELECT active_nonce FROM sender_review_ci.scope_fences"
        ), [("a" * 32,)])

    def test_unknown_hold_is_one_way_and_never_releases_fence(self):
        self.seed()
        self.assertEqual(self.hold(), (False, "no-started-review-attempt"))
        self.assertTrue(self.start()[0])
        self.assertEqual(self.hold(), (True, "unknown-held-no-retry-or-release"))
        self.assertFalse(self.hold()[0])
        self.assertFalse(self.start()[0])
        self.assertEqual(self.query(
            "SELECT kind FROM sender_review_ci.simulated_attempt_events "
            "ORDER BY event_id"
        ), [("simulated_attempt_started",), ("simulated_unknown_held",)])
        self.assertEqual(self.query(
            "SELECT state FROM sender_review_ci.review_intents"
        ), [("hold_unknown",)])
        self.assertEqual(self.query(
            "SELECT fence,active_nonce FROM sender_review_ci.scope_fences"
        ), [(1, "a" * 32)])
        self.assertEqual(self.query(
            "SELECT kind FROM sender_review_ci.review_events ORDER BY event_id"
        ), [("review_recorded",), ("unknown_held",)])

    def test_wrong_account_fence_coin_and_nonce_never_start(self):
        self.seed()
        for values in (
            {"account": "0x" + "2" * 40},
            {"coin": "AVAX"},
            {"nonce": "b" * 32},
            {"fence": 0},
            {"fence": 2},
        ):
            with self.subTest(values=values):
                self.assertFalse(self.start(**values)[0])
                self.assertFalse(self.hold(**values)[0])
        self.assertEqual(self.query(
            "SELECT count(*) FROM sender_review_ci.simulated_attempt_events"
        ), [(0,)])

    def test_unsigned_journal_intent_cannot_start_without_signed_evidence(self):
        from sender_review.test_ci_journal_postgres import record
        self.assertTrue(record()[0])
        self.assertEqual(self.start(), (False, "unverified-or-unheld-review-intent"))
        self.assertEqual(self.query(
            "SELECT count(*) FROM sender_review_ci.simulated_attempt_events"
        ), [(0,)])

    def test_competing_workers_only_one_simulated_start(self):
        self.seed()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(self.start) for _ in range(3)]
            results = [future.result(timeout=8) for future in futures]
        self.assertEqual(sum(bool(row[0]) for row in results), 1)
        self.assertEqual(self.query(
            "SELECT count(*) FROM sender_review_ci.simulated_attempt_events"
        ), [(1,)])

    def test_append_only_attempt_events_reject_changes(self):
        self.seed()
        self.assertTrue(self.start()[0])
        for sql in (
            "UPDATE sender_review_ci.simulated_attempt_events "
            "SET kind='simulated_unknown_held'",
            "DELETE FROM sender_review_ci.simulated_attempt_events",
        ):
            with self.subTest(sql=sql):
                with connect() as conn:
                    with self.assertRaises(psycopg.errors.RaiseException):
                        conn.execute(sql)
        self.assertEqual(self.query(
            "SELECT kind FROM sender_review_ci.simulated_attempt_events"
        ), [("simulated_attempt_started",)])

    def test_failed_transition_does_not_partially_record_unknown_hold(self):
        self.seed()
        self.assertTrue(self.start()[0])
        with connect() as conn:
            conn.execute(
                "ALTER TABLE sender_review_ci.simulated_attempt_events "
                "ADD CONSTRAINT forced_failed_unknown_hold "
                "CHECK (kind <> 'simulated_unknown_held') NOT VALID"
            )
        try:
            with connect() as conn:
                with self.assertRaises(psycopg.errors.CheckViolation):
                    conn.execute(
                        "SELECT held,reason FROM "
                        "sender_review_ci.hold_simulated_attempt_unknown"
                        "(%s,%s,%s,%s)", (ACCOUNT, "SOL", "a" * 32, 1)
                    )
            self.assertEqual(self.query(
                "SELECT state FROM sender_review_ci.review_intents"
            ), [("review_only",)])
            self.assertEqual(self.query(
                "SELECT kind FROM sender_review_ci.review_events"
            ), [("review_recorded",)])
        finally:
            with connect() as conn:
                conn.execute(
                    "ALTER TABLE sender_review_ci.simulated_attempt_events "
                    "DROP CONSTRAINT forced_failed_unknown_hold"
                )
        self.assertTrue(self.hold()[0])


if __name__ == "__main__":
    unittest.main()
