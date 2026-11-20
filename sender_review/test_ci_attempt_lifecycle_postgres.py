"""Disposable PostgreSQL test-only simulated attempt lifecycle; NO orders."""
import concurrent.futures
import os
import subprocess
import sys
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

    def test_worker_crash_after_durable_start_forces_new_process_to_hold(self):
        # Two independent Python worker processes simulate interruption
        # between a durably COMMITTED fake start and its unknown outcome.
        # No exchange sender exists; the child only accesses disposable CI.
        self.seed()
        child_code = """
import os
import sys
from sender_review.test_ci_journal_postgres import ACCOUNT, connect

action = sys.argv[1]
with connect() as db:
    if action == "start":
        row = db.execute(
            "SELECT recorded,reason FROM "
            "sender_review_ci.record_simulated_attempt_start(%s,%s,%s,%s)",
            (ACCOUNT, "SOL", "a" * 32, 1),
        ).fetchone()
        if row != (True, "simulated-start-recorded-no-send"):
            os._exit(21)
    elif action == "restart":
        row = db.execute(
            "SELECT recorded,reason FROM "
            "sender_review_ci.record_simulated_attempt_start(%s,%s,%s,%s)",
            (ACCOUNT, "SOL", "a" * 32, 1),
        ).fetchone()
        if row != (False, "simulated-attempt-already-recorded"):
            os._exit(22)
        row = db.execute(
            "SELECT held,reason FROM "
            "sender_review_ci.hold_simulated_attempt_unknown(%s,%s,%s,%s)",
            (ACCOUNT, "SOL", "a" * 32, 1),
        ).fetchone()
        if row != (True, "unknown-held-no-retry-or-release"):
            os._exit(23)
    else:
        os._exit(24)
# Abrupt process exit, not a clean application shutdown. All earlier
# SQL calls used autocommit and must persist across that process exit.
os._exit(0)
"""
        for action in ("start", "restart"):
            with self.subTest(worker=action):
                worker = subprocess.run(
                    [sys.executable, "-c", child_code, action],
                    capture_output=True, text=True, timeout=10,
                    check=False,
                )
                self.assertEqual(
                    worker.returncode, 0,
                    "mock worker failed: " + worker.stderr[-1000:],
                )
                if action == "start":
                    self.assertEqual(self.query(
                        "SELECT state FROM sender_review_ci.review_intents"
                    ), [("review_only",)])
                    self.assertEqual(self.query(
                        "SELECT kind FROM sender_review_ci.simulated_attempt_events"
                    ), [("simulated_attempt_started",)])
        self.assertEqual(self.query(
            "SELECT state FROM sender_review_ci.review_intents"
        ), [("hold_unknown",)])
        self.assertEqual(self.query(
            "SELECT kind FROM sender_review_ci.simulated_attempt_events "
            "ORDER BY event_id"
        ), [("simulated_attempt_started",), ("simulated_unknown_held",)])
        self.assertEqual(self.query(
            "SELECT fence,active_nonce FROM sender_review_ci.scope_fences"
        ), [(1, "a" * 32)])
        self.assertFalse(self.start()[0])
        self.assertFalse(self.hold()[0])
        from sender_review.test_ci_journal_postgres import record
        collision = record(
            bot="aggressive", coin="SOL", nonce="b" * 32
        )
        self.assertFalse(collision[0])
        self.assertEqual(collision[2], "active-scope-held")
        self.assertEqual(self.query(
            "SELECT count(*) FROM sender_review_ci.review_intents"
        ), [(1,)])

    def test_independent_session_sees_unresolved_attempt_after_crash(self):
        # No restart or sender action is needed to surface the unresolved
        # fake attempt. A fresh DB connection sees one stable incident,
        # then sees its one-way transition to UNKNOWN_HELD.
        self.seed()
        self.assertEqual(self.query(
            "SELECT count(*) FROM sender_review_ci.simulated_unresolved_attempts"
        ), [(0,)])
        self.assertTrue(self.start()[0])
        with connect() as observer:
            first = observer.execute(
                "SELECT bot,coin,request_nonce,fence,journal_state,"
                "incident_state,fence_still_held "
                "FROM sender_review_ci.simulated_unresolved_attempts"
            ).fetchall()
        self.assertEqual(first, [(
            "daily", "SOL", "a" * 32, 1, "review_only",
            "STARTED_OUTCOME_UNCONFIRMED", True,
        )])
        self.assertTrue(self.hold()[0])
        with connect() as observer:
            second = observer.execute(
                "SELECT bot,coin,request_nonce,fence,journal_state,"
                "incident_state,fence_still_held "
                "FROM sender_review_ci.simulated_unresolved_attempts"
            ).fetchall()
        self.assertEqual(second, [(
            "daily", "SOL", "a" * 32, 1, "hold_unknown",
            "UNKNOWN_HELD", True,
        )])
        self.assertEqual(self.query(
            "SELECT count(*) FROM sender_review_ci.simulated_unresolved_attempts"
        ), [(1,)])
        self.assertFalse(self.start()[0])
        self.assertFalse(self.hold()[0])

    def test_incident_view_flags_missing_or_changed_fence(self):
        self.seed()
        self.assertTrue(self.start()[0])
        query = (
            "SELECT fence_still_held,incident_attention FROM "
            "sender_review_ci.simulated_unresolved_attempts"
        )
        self.assertEqual(self.query(query), [
            (True, "CRITICAL_OUTCOME_UNCONFIRMED")
        ])
        with connect() as db:
            db.execute(
                "UPDATE sender_review_ci.scope_fences "
                "SET active_nonce=NULL WHERE coin='SOL'"
            )
        self.assertEqual(self.query(query), [
            (False, "CRITICAL_FENCE_MISSING_OR_CHANGED")
        ])
        # Restore ONLY within this disposable test for later assertions.
        with connect() as db:
            db.execute(
                "UPDATE sender_review_ci.scope_fences "
                "SET active_nonce=%s WHERE coin='SOL'", ("a" * 32,)
            )
        self.assertTrue(self.hold()[0])
        self.assertEqual(self.query(query), [
            (True, "CRITICAL_UNKNOWN_OUTCOME")
        ])

    def test_incident_view_detects_missing_unknown_hold_event(self):
        # Inject a deliberately inconsistent state into disposable CI.
        # A missing event must never be presented as a settled order.
        self.seed()
        self.assertTrue(self.start()[0])
        with connect() as db:
            db.execute(
                "UPDATE sender_review_ci.review_intents "
                "SET state='hold_unknown' WHERE coin='SOL'"
            )
        self.assertEqual(self.query(
            "SELECT incident_attention,fence_still_held "
            "FROM sender_review_ci.simulated_unresolved_attempts"
        ), [("CRITICAL_HOLD_EVENT_MISSING", True)])

    def test_unknown_held_without_start_is_visible_as_critical(self):
        # Corrupt only disposable CI data to simulate a missing attempt
        # start event after an unknown transition. This record must not
        # disappear from the incident view or imply a safe retry.
        self.seed()
        with connect() as db:
            db.execute(
                "UPDATE sender_review_ci.review_intents "
                "SET state='hold_unknown' WHERE coin='SOL'"
            )
        self.assertEqual(self.query(
            "SELECT incident_state,incident_attention,"
            "fence_still_held,simulated_started_at IS NULL "
            "FROM sender_review_ci.simulated_unresolved_attempts"
        ), [(
            "UNKNOWN_HELD_MISSING_START",
            "CRITICAL_START_EVENT_MISSING", True, True,
        )])
        self.assertFalse(self.start()[0])
        self.assertFalse(self.hold()[0])
        self.assertEqual(self.query(
            "SELECT count(*) FROM sender_review_ci.simulated_attempt_events"
        ), [(0,)])
        self.assertEqual(self.query(
            "SELECT active_nonce FROM sender_review_ci.scope_fences"
        ), [("a" * 32,)])

    def test_unstarted_review_only_intent_is_not_called_attempt(self):
        self.seed()
        self.assertEqual(self.query(
            "SELECT count(*) FROM sender_review_ci.simulated_unresolved_attempts"
        ), [(0,)])
        self.assertTrue(self.start()[0])
        self.assertEqual(self.query(
            "SELECT incident_attention "
            "FROM sender_review_ci.simulated_unresolved_attempts"
        ), [("CRITICAL_OUTCOME_UNCONFIRMED",)])

    def test_untrusted_role_cannot_read_unresolved_attempt_view(self):
        # View access is denied even for a separate created read-only role.
        # No public observer endpoint or service authentication exists.
        with connect() as conn:
            self.assertFalse(conn.execute(
                "SELECT EXISTS ("
                "SELECT 1 FROM pg_class c "
                "CROSS JOIN LATERAL aclexplode(COALESCE("
                "c.relacl,acldefault('r',c.relowner))) acl "
                "WHERE c.oid='sender_review_ci.simulated_unresolved_attempts'::regclass "
                "AND acl.grantee=0 AND acl.privilege_type='SELECT')"
            ).fetchone()[0])
            self.assertEqual(conn.execute(
                "SELECT reloptions FROM pg_class WHERE oid="
                "'sender_review_ci.simulated_unresolved_attempts'::regclass"
            ).fetchone()[0], ["security_invoker=true"])

    def test_untrusted_db_role_denied_recovery_view_and_functions(self):
        # A deliberately unprivileged, NOLOGIN test role must not obtain
        # the CI incident view or simulated state-mutation functions.
        # This checks only the disposable DB privilege setup, not host ACLs.
        role = "sender_review_attempt_untrusted"
        with connect() as admin:
            admin.execute(
                "CREATE ROLE " + role + " NOLOGIN NOSUPERUSER "
                "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            )
        try:
            self.seed()
            self.assertTrue(self.start()[0])
            signatures = (
                "sender_review_ci.record_simulated_attempt_start("
                "text,text,text,bigint)",
                "sender_review_ci.hold_simulated_attempt_unknown("
                "text,text,text,bigint)",
            )
            with connect() as admin:
                self.assertFalse(admin.execute(
                    "SELECT has_schema_privilege(%s,'sender_review_ci','USAGE')",
                    (role,)
                ).fetchone()[0])
                self.assertFalse(admin.execute(
                    "SELECT has_table_privilege(%s,"
                    "'sender_review_ci.simulated_unresolved_attempts','SELECT')",
                    (role,)
                ).fetchone()[0])
                self.assertFalse(admin.execute(
                    "SELECT has_table_privilege(%s,"
                    "'sender_review_ci.simulated_attempt_events','SELECT')",
                    (role,)
                ).fetchone()[0])
                for signature in signatures:
                    with self.subTest(function=signature):
                        self.assertFalse(admin.execute(
                            "SELECT has_function_privilege(%s,%s,'EXECUTE')",
                            (role, signature)
                        ).fetchone()[0])
                admin.execute("SET ROLE " + role)
                try:
                    for query in (
                        "SELECT * FROM "
                        "sender_review_ci.simulated_unresolved_attempts",
                        "SELECT * FROM sender_review_ci."
                        "record_simulated_attempt_start("
                        "'0x1111111111111111111111111111111111111111',"
                        "'SOL','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',1)",
                        "SELECT * FROM sender_review_ci."
                        "hold_simulated_attempt_unknown("
                        "'0x1111111111111111111111111111111111111111',"
                        "'SOL','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',1)",
                    ):
                        with self.subTest(query=query):
                            with self.assertRaises(
                                psycopg.errors.InsufficientPrivilege
                            ):
                                admin.execute(query)
                finally:
                    admin.execute("RESET ROLE")
            self.assertEqual(self.query(
                "SELECT state FROM sender_review_ci.review_intents"
            ), [("review_only",)])
            self.assertEqual(self.query(
                "SELECT kind FROM sender_review_ci.simulated_attempt_events"
            ), [("simulated_attempt_started",)])
        finally:
            with connect() as admin:
                admin.execute("DROP ROLE IF EXISTS " + role)

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
