"""Disposable PG-only account-wide incident quarantine review: NO orders."""
import concurrent.futures
import os
from pathlib import Path
import unittest

import psycopg

from sender_review.ci_only_identity_bridge import (
    inspect_and_record_signed_fixture_offline,
)
from sender_review.test_ci_journal_postgres import (
    ACCOUNT, CI_MARKER, SQL, connect, record,
)
from sender_review.test_offline_oidc_identity_fixture import (
    SignedOidcFixtureTests, POLICY, NOW,
)

PROTECTION = Path(__file__).with_name("ci_only_protection_reentry_holds.sql")
QUARANTINE = Path(__file__).with_name("ci_only_account_wide_quarantine.sql")
EVENTS = "sender_review_ci.simulated_account_quarantine_events"
ACCOUNT2 = "0x" + "2" * 40


@unittest.skipUnless(
    os.environ.get(CI_MARKER) == "1"
    and os.environ.get("PGDATABASE") == "sender_review_test"
    and os.environ.get("PGHOST") == "127.0.0.1",
    "Disposable local PostgreSQL CI only",
)
class AccountWideQuarantinePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SignedOidcFixtureTests.setUpClass()
        cls.fixture = SignedOidcFixtureTests()
        cls.keys = SignedOidcFixtureTests.keys
        with connect() as db:
            db.execute(SQL.read_text("utf-8"))
            db.execute(PROTECTION.read_text("utf-8"))
            db.execute(QUARANTINE.read_text("utf-8"))

    def setUp(self):
        with connect() as db:
            db.execute(
                "TRUNCATE sender_review_ci.fixture_identity_receipts,"
                "sender_review_ci.review_events,"
                "sender_review_ci.review_intents,"
                "sender_review_ci.scope_fences RESTART IDENTITY CASCADE"
            )

    @staticmethod
    def rows(sql, args=()):
        with connect() as db:
            return db.execute(sql, args).fetchall()

    def signed(self, bot="daily", coin="SOL", nonce="a"*32):
        body = (
            b'{"version":1,"action":"open_long","side":"long",'
            b'"coin":"' + coin.encode("ascii") +
            b'","rounded_size":"0.16","requested_leverage":2,'
            b'"request_nonce":"' + nonce.encode("ascii") + b'"}'
        )
        result = inspect_and_record_signed_fixture_offline(
            token=self.fixture.token(bot, jti="quarantine-"+bot+"-"+coin),
            body=body, policy=POLICY, fixture_keys=self.keys,
            fixture_now_seconds=NOW, fixed_test_account=ACCOUNT,
            db_password=os.environ["PGPASSWORD"],
        )
        self.assertTrue(result.journal_recorded)
        self.assertFalse(result.submit_authorized)
        return result.assigned_fence

    def hold_unknown(self, coin="SOL", nonce="a"*32, fence=1):
        with connect() as db:
            return db.execute(
                "SELECT sender_review_ci.hold_uncertain(%s,%s,%s,%s)",
                (ACCOUNT,coin,nonce,fence),
            ).fetchone()[0]

    def test_unknown_journal_fences_all_other_coins_and_bots(self):
        self.assertTrue(record()[0])
        self.assertTrue(self.hold_unknown())
        self.assertEqual(self.rows(
            "SELECT bot,coin,reason FROM " + EVENTS
        ), [("daily","SOL","JOURNAL_UNKNOWN")])
        for bot, coin, nonce in (
            ("daily","AVAX","b"*32),
            ("intraday","LINK","c"*32),
            ("aggressive","SUI","d"*32),
            ("aggressive","SOL","e"*32),
        ):
            with self.subTest(bot=bot,coin=coin):
                result=record(bot,coin,nonce)
                self.assertFalse(result[0])
                self.assertEqual(result[2], "duplicate-claim-held"
                                 if coin!="SOL" else "active-scope-held")
        self.assertEqual(self.rows(
            "SELECT bot,coin,state FROM sender_review_ci.review_intents"
        ), [("daily","SOL","hold_unknown")])
        self.assertEqual(self.rows(
            "SELECT unresolved_incident_count,affected_coins,review_state "
            "FROM sender_review_ci.simulated_account_quarantine_review"
        ), [(1,1,"ACCOUNT_WIDE_QUARANTINE_HOLD_NO_TRADING_AUTHORITY")])
        self.assertFalse(self.hold_unknown())

    def test_all_protection_outcomes_quarantine_account_including_closed_claim(self):
        for label in ("pending_exit","unknown_ack","partial_fill","claimed_closed"):
            with self.subTest(label=label):
                self.setUp()
                self.signed()
                with connect() as db:
                    result=db.execute(
                        "SELECT recorded,reason FROM "
                        "sender_review_ci.record_ci_protection_reentry_hold("
                        "%s,%s,%s,%s,%s,%s,%s)",
                        (ACCOUNT,"daily","SOL","long","a"*32,1,label),
                    ).fetchone()
                self.assertEqual(result, (
                    True,"durable-review-only-protection-HOLD"
                ))
                self.assertEqual(self.rows(
                    "SELECT reason FROM " + EVENTS
                ), [("PROTECTION_"+label.upper(),)])
                self.assertFalse(record("aggressive","AVAX","b"*32)[0])
                self.assertEqual(self.rows(
                    "SELECT count(*) FROM sender_review_ci.review_intents"
                ), [(1,)])

    def test_interrupted_signed_handoff_blocks_other_coin_without_event(self):
        # A signed synthetic request is recorded before the separate
        # protection-HOLD step. An interrupted second stage does not
        # insert a quarantine event, yet must still deny ALL bot entries.
        self.signed()
        self.assertEqual(self.rows("SELECT count(*) FROM " + EVENTS), [(0,)])
        self.assertEqual(self.rows(
            "SELECT explicit_incident_count,critical_handoff_count,review_state "
            "FROM sender_review_ci.simulated_account_admission_review"
        ), [(0,1,"ACCOUNT_ADMISSION_FROZEN_CI_REVIEW_ONLY")])
        for bot,coin,nonce in (
            ("daily","AVAX","b"*32),
            ("intraday","LINK","c"*32),
            ("aggressive","SUI","d"*32),
        ):
            with self.subTest(bot=bot,coin=coin):
                denied = record(bot,coin,nonce)
                self.assertEqual(denied[0],False)
                self.assertEqual(denied[2],"duplicate-claim-held")
        self.assertEqual(self.rows(
            "SELECT COUNT(*) FROM sender_review_ci.review_intents"
        ), [(1,)])
        self.assertEqual(self.rows(
            "SELECT COUNT(*) FROM sender_review_ci.fixture_request_evidence"
        ), [(1,)])
        self.assertEqual(self.rows("SELECT count(*) FROM "+EVENTS), [(0,)])

    def test_interrupted_handoff_racing_three_bots_all_denied(self):
        self.signed()
        jobs=(("daily","AVAX","b"*32),("intraday","LINK","c"*32),
              ("aggressive","SUI","d"*32))
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            responses=list(pool.map(lambda params:record(*params),jobs))
        self.assertEqual([result[0] for result in responses],
                         [False,False,False])
        self.assertEqual(self.rows(
            "SELECT count(*) FROM sender_review_ci.review_intents"
        ), [(1,)])

    def test_corrupted_signed_scope_fence_blocks_other_coins(self):
        self.signed()
        with connect() as db:
            db.execute(
                "UPDATE sender_review_ci.scope_fences "
                "SET active_nonce=NULL WHERE account=%s AND coin='SOL'",
                (ACCOUNT,),
            )
        self.assertEqual(self.rows(
            "SELECT review_state FROM "
            "sender_review_ci.simulated_protection_handoff_audit"
        ), [("CRITICAL_FENCE_MISSING_OR_CHANGED",)])
        self.assertFalse(record("intraday","AVAX","b"*32)[0])
        self.assertEqual(self.rows(
            "SELECT critical_handoff_count FROM "
            "sender_review_ci.simulated_account_admission_review"
        ), [(1,)])

    def test_healthy_protection_hold_does_not_forge_clearance(self):
        # A fake protection hold creates an explicit quarantine event.
        # The handoff audit then becomes locally coherent, yet admission
        # must still be frozen across coins and identities.
        self.signed()
        with connect() as db:
            recorded=db.execute(
                "SELECT recorded FROM "
                "sender_review_ci.record_ci_protection_reentry_hold("
                "%s,%s,%s,%s,%s,%s,%s)",
                (ACCOUNT,"daily","SOL","long","a"*32,1,"claimed_closed"),
            ).fetchone()[0]
        self.assertTrue(recorded)
        self.assertEqual(self.rows(
            "SELECT explicit_incident_count,critical_handoff_count "
            "FROM sender_review_ci.simulated_account_admission_review"
        ), [(1,0)])
        self.assertFalse(record("aggressive","AVAX","b"*32)[0])

    def test_separate_account_does_not_inherit_quarantine(self):
        self.assertTrue(record()[0])
        self.assertTrue(self.hold_unknown())
        with connect() as db:
            accepted=db.execute(
                "SELECT recorded,assigned_fence,reason FROM "
                "sender_review_ci.record_review_only("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                (ACCOUNT2,"intraday","AVAX","open_long","long","0.16",2,"b"*32),
            ).fetchone()
        self.assertEqual(accepted,(True,1,"persisted-review-only-HOLD"))
        self.assertEqual(self.rows(
            "SELECT account,coin FROM sender_review_ci.review_intents "
            "ORDER BY account"
        ), [(ACCOUNT,"SOL"),(ACCOUNT2,"AVAX")])

    def test_racing_bots_on_different_coins_after_quarantine_denied(self):
        self.assertTrue(record()[0])
        self.assertTrue(self.hold_unknown())
        jobs=(("daily","AVAX","b"*32),("intraday","LINK","c"*32),
              ("aggressive","SUI","d"*32))
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda v:record(*v),jobs))
        self.assertTrue(all(row[0] is False for row in results))
        self.assertEqual(self.rows(
            "SELECT COUNT(*) FROM sender_review_ci.review_intents"
        ), [(1,)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM "+EVENTS),[(1,)])

    def test_ordinary_updates_and_deletes_cannot_erase_quarantine(self):
        self.assertTrue(record()[0])
        self.assertTrue(self.hold_unknown())
        for command in (
            "DELETE FROM "+EVENTS,
            "UPDATE "+EVENTS+" SET reason='PROTECTION_UNKNOWN_ACK'",
        ):
            with self.subTest(command=command):
                with connect() as db:
                    with self.assertRaises(psycopg.errors.RaiseException):
                        db.execute(command)
        self.assertFalse(record("intraday","AVAX","b"*32)[0])

    def test_no_public_read_or_function_execution_rights(self):
        with connect() as db:
            self.assertFalse(db.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_class c "
                "CROSS JOIN LATERAL aclexplode(COALESCE("
                "c.relacl,acldefault('r',c.relowner))) acl "
                "WHERE c.oid=%s::regclass AND acl.grantee=0 "
                "AND acl.privilege_type='SELECT')",
                (EVENTS,),
            ).fetchone()[0])
            self.assertEqual(db.execute(
                "SELECT reloptions FROM pg_class WHERE "
                "oid='sender_review_ci.simulated_account_quarantine_review'"
                "::regclass"
            ).fetchone()[0], ["security_invoker=true"])

    def test_quarantine_sql_is_ci_only_no_trade_or_release(self):
        sql=QUARANTINE.read_text("utf-8")
        self.assertIn("current_database() <> 'sender_review_test'",sql)
        self.assertIn("BEFORE INSERT ON sender_review_ci.review_intents",sql)
        self.assertIn("AFTER UPDATE OF state",sql)
        self.assertIn("AFTER INSERT ON sender_review_ci.simulated_protection",sql)
        for forbidden in ("market_open(","market_close(","HL_PRIVATE_KEY",
                          "submit_authorized","release_claim(","retry_order("):
            self.assertNotIn(forbidden,sql)


if __name__ == "__main__":
    unittest.main()
