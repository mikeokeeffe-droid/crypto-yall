"""Disposable-only integration: signed fixture, nonce receipt, journal HOLD."""
import concurrent.futures
import hashlib
import json
import os
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

    def test_exact_bytes_and_fixture_identity_are_bound_atomically(self):
        token = self.fixture.token("intraday", jti="bound-fixture-001")
        body = self.body(nonce="f"*32)
        r = self.submit(token=token, body=body)
        self.assertTrue(r.journal_recorded)
        evidence = self.rows(
            "SELECT e.account,e.bot,e.jti,e.request_nonce,"
            "e.token_sha256,e.body_sha256,e.body_length,i.coin,i.fence "
            "FROM sender_review_ci.fixture_request_evidence e "
            "JOIN sender_review_ci.review_intents i ON i.id=e.intent_id"
        )
        self.assertEqual(evidence, [(
            ACCOUNT, "intraday", "bound-fixture-001", "f"*32,
            hashlib.sha256(token.encode("ascii")).hexdigest(),
            hashlib.sha256(body).hexdigest(), len(body), "SOL", 1,
        )])
        self.assertFalse(r.runtime_identity_authenticated)
        self.assertFalse(r.submit_authorized)

    def test_mismatched_bot_nonce_or_receipt_cannot_forge_evidence(self):
        from sender_review.test_ci_journal_postgres import record
        token = self.fixture.token("daily", jti="bound-fixture-match-001")
        request_body = self.body(nonce="e"*32)
        self.assertTrue(self.submit(token=token, body=request_body).journal_recorded)
        # An independent review intent on AVAX is deliberately left WITHOUT
        # evidence, so the FK (not a duplicate evidence PK) must reject a
        # forged link between that intent and another bot or receipt.
        review = record(bot="intraday", coin="AVAX", nonce="d"*32)
        self.assertTrue(review[0])
        with connect() as conn:
            conn.execute(
                "INSERT INTO sender_review_ci.fixture_identity_receipts "
                "(environment,account,jti,bot,request_nonce) "
                "VALUES ('testnet',%s,%s,%s,%s)",
                (ACCOUNT, "unbound-fixture-002", "intraday", "d"*32),
            )
        intent_id = self.rows(
            "SELECT id FROM sender_review_ci.review_intents "
            "WHERE coin='AVAX'"
        )[0][0]
        original = self.rows(
            "SELECT intent_id,token_sha256,body_sha256 FROM "
            "sender_review_ci.fixture_request_evidence"
        )
        cases = (
            ("daily", "unbound-fixture-002", "d"*32),
            ("intraday", "bound-fixture-match-001", "d"*32),
            ("intraday", "unbound-fixture-002", "e"*32),
            ("daily", "bound-fixture-match-001", "e"*32),
            ("intraday", "nonexistent-fixture", "d"*32),
        )
        for index, (bot, jti, nonce) in enumerate(cases):
            with self.subTest(bot=bot, jti=jti, nonce=nonce):
                # Composite FK and unique JTI/nonce constraints jointly deny
                # forged evidence. The first case has no uniqueness collision
                # and must specifically fail its intent/bot composite FK.
                expected_error = (
                    psycopg.errors.ForeignKeyViolation if index == 0
                    else psycopg.errors.IntegrityError
                )
                with connect() as conn:
                    with self.assertRaises(expected_error):
                        conn.execute(
                            "INSERT INTO sender_review_ci.fixture_request_evidence "
                            "(intent_id,environment,account,request_nonce,bot,"
                            "jti,token_sha256,body_sha256,body_length) "
                            "VALUES (%s,'testnet',%s,%s,%s,%s,%s,%s,%s)",
                            (intent_id, ACCOUNT, nonce, bot, jti,
                             hashlib.sha256(token.encode()).hexdigest(),
                             hashlib.sha256(request_body).hexdigest(),
                             len(request_body)),
                        )
        self.assertEqual(original, self.rows(
            "SELECT intent_id,token_sha256,body_sha256 FROM "
            "sender_review_ci.fixture_request_evidence"
        ))

    def test_changed_body_or_token_replay_does_not_modify_evidence(self):
        token = self.fixture.token("daily", jti="bound-fixture-002")
        body = self.body(nonce="c"*32)
        self.assertTrue(self.submit(token=token, body=body).journal_recorded)
        before = self.rows(
            "SELECT token_sha256,body_sha256 FROM "
            "sender_review_ci.fixture_request_evidence"
        )
        # Same signed token, semantically identical but different raw bytes.
        reformatted = json.dumps(json.loads(body), separators=(",", ":")).encode()
        self.assertNotEqual(body, reformatted)
        self.assertEqual(self.submit(token=token, body=reformatted).state, "hold")
        # A new signed token cannot reuse a consumed request nonce.
        different_token = self.fixture.token("daily", jti="bound-fixture-003")
        self.assertEqual(
            self.submit(token=different_token, body=body).state, "hold"
        )
        self.assertEqual(before, self.rows(
            "SELECT token_sha256,body_sha256 FROM "
            "sender_review_ci.fixture_request_evidence"
        ))
        self.assertEqual(len(self.rows(
            "SELECT 1 FROM sender_review_ci.fixture_request_evidence"
        )), 1)

    def test_evidence_cannot_be_modified_or_deleted(self):
        token = self.fixture.token("aggressive", jti="bound-fixture-004")
        self.assertTrue(self.submit(token=token).journal_recorded)
        with connect() as conn:
            with self.assertRaises(psycopg.errors.RaiseException):
                conn.execute(
                    "UPDATE sender_review_ci.fixture_request_evidence "
                    "SET body_sha256=%s", ("0"*64,)
                )
            with self.assertRaises(psycopg.errors.RaiseException):
                conn.execute(
                    "DELETE FROM sender_review_ci.fixture_request_evidence"
                )
        self.assertEqual(len(self.rows(
            "SELECT 1 FROM sender_review_ci.fixture_request_evidence"
        )), 1)

    def test_invalid_or_contended_requests_leave_no_extra_evidence(self):
        valid = self.submit(
            token=self.fixture.token("daily", jti="bound-fixture-005")
        )
        self.assertTrue(valid.journal_recorded)
        denied = self.submit(
            token=self.fixture.token("intraday", jti="bound-fixture-006"),
            body=self.body(nonce="b"*32),
        )
        self.assertEqual(denied.state, "hold")
        self.assertEqual(len(self.rows(
            "SELECT 1 FROM sender_review_ci.fixture_request_evidence"
        )), 1)
        self.assertEqual(len(self.rows(
            "SELECT 1 FROM sender_review_ci.fixture_identity_receipts"
        )), 1)
        self.assertEqual(len(self.rows(
            "SELECT 1 FROM sender_review_ci.review_intents"
        )), 1)

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

    def test_three_signed_bots_same_nonce_cross_coin_single_evidence(self):
        # Distinct fake signed JTI values and bot identities race with the
        # SAME account-wide nonce on different coins. The fixture receipt
        # must be consumed in the journal transaction and the losing
        # submissions must never create empty scope rows or orphaned proof.
        jobs = (
            ("daily", "SOL", "three-bots-cross-coin-daily"),
            ("intraday", "AVAX", "three-bots-cross-coin-intraday"),
            ("aggressive", "LINK", "three-bots-cross-coin-aggressive"),
        )
        submissions = [
            (bot, coin, jti, self.fixture.token(bot, jti=jti),
             self.body(nonce="d" * 32, coin=coin))
            for bot, coin, jti in jobs
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [
                pool.submit(self.submit, token=token, body=body)
                for _, _, _, token, body in submissions
            ]
            results = [f.result(timeout=10) for f in futures]
        self.assertEqual(sum(r.journal_recorded for r in results), 1)
        self.assertTrue(all(
            not r.runtime_identity_authenticated
            and not r.request_authorized
            and not r.submit_authorized
            and not r.close_authorized
            for r in results
        ))
        winner_index = next(
            index for index, r in enumerate(results) if r.journal_recorded
        )
        winning_bot, winning_coin, winning_jti, token, body = (
            submissions[winner_index]
        )
        self.assertEqual(self.rows(
            "SELECT bot,coin,request_nonce FROM "
            "sender_review_ci.review_intents"
        ), [(winning_bot, winning_coin, "d" * 32)])
        self.assertEqual(self.rows(
            "SELECT bot,jti,request_nonce FROM "
            "sender_review_ci.fixture_identity_receipts"
        ), [(winning_bot, winning_jti, "d" * 32)])
        self.assertEqual(self.rows(
            "SELECT e.bot,e.jti,e.body_sha256,e.token_sha256,i.coin "
            "FROM sender_review_ci.fixture_request_evidence e "
            "JOIN sender_review_ci.review_intents i ON i.id=e.intent_id"
        ), [(
            winning_bot, winning_jti,
            hashlib.sha256(body).hexdigest(),
            hashlib.sha256(token.encode("ascii")).hexdigest(),
            winning_coin,
        )])
        self.assertEqual(self.rows(
            "SELECT coin,fence,active_nonce FROM "
            "sender_review_ci.scope_fences"
        ), [(winning_coin, 1, "d" * 32)])
        self.assertEqual(self.rows(
            "SELECT kind FROM sender_review_ci.review_events"
        ), [("review_recorded",)])
        for index, (_, coin, _, _, _) in enumerate(submissions):
            if index != winner_index:
                self.assertFalse(results[index].journal_recorded)
                self.assertEqual(results[index].state, "hold")
                self.assertNotEqual(coin, winning_coin)

        # Failed attempts did not consume competing identity receipts or
        # poison other coin scopes: a new nonce and fresh fixture token can
        # still create its own review-only HOLD, never an executable send.
        losing_bot, losing_coin, _, _, _ = submissions[
            (winner_index + 1) % len(submissions)
        ]
        fresh = self.submit(
            token=self.fixture.token(
                losing_bot, jti="fresh-cross-coin-review-001"
            ),
            body=self.body(nonce="e" * 32, coin=losing_coin),
        )
        self.assertTrue(fresh.journal_recorded)
        self.assertFalse(fresh.submit_authorized)
        self.assertEqual(self.rows(
            "SELECT count(*) FROM sender_review_ci.fixture_identity_receipts"
        ), [(2,)])
        self.assertEqual(self.rows(
            "SELECT count(*) FROM sender_review_ci.fixture_request_evidence"
        ), [(2,)])

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
