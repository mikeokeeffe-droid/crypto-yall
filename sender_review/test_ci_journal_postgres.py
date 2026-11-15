"""S2 isolated, disposable PostgreSQL journal acceptance tests.

Runs only against GitHub Actions' transient PostgreSQL service. Never connect
to real databases. This tests state serialization, not signer authority,
workload authentication, exchange acknowledgements, or actual fill ownership.
"""
import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys
import unittest

import psycopg

ACCOUNT = "0x" + "1" * 40
CI_MARKER = "SENDER_REVIEW_DISPOSABLE_CI"
ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "sender_review" / "ci_only_journal.sql"


def connect():
    return psycopg.connect(
        host="127.0.0.1", port=5432, dbname="sender_review_test",
        user="postgres", password=os.environ["PGPASSWORD"],
        autocommit=True,
    )


def record(bot="daily", coin="SOL", nonce="a" * 32,
           action="open_long", side="long", size="0.16", leverage=2):
    with connect() as conn:
        return conn.execute(
            "select recorded,assigned_fence,reason "
            "from sender_review_ci.record_review_only("
            "%s,%s,%s,%s,%s,%s,%s,%s)",
            (ACCOUNT, bot, coin, action, side, size, leverage, nonce),
        ).fetchone()


@unittest.skipUnless(
    os.environ.get(CI_MARKER) == "1"
    and os.environ.get("PGDATABASE") == "sender_review_test"
    and os.environ.get("PGHOST") == "127.0.0.1",
    "Only a named disposable local PostgreSQL test is allowed",
)
class SenderJournalPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connect() as conn:
            conn.execute(SQL.read_text(encoding="utf-8"))

    def setUp(self):
        with connect() as conn:
            conn.execute(
                "truncate sender_review_ci.fixture_identity_receipts,"
                "sender_review_ci.review_events,"
                "sender_review_ci.review_intents,"
                "sender_review_ci.scope_fences restart identity cascade"
            )

    def query(self, sql, params=()):
        with connect() as conn:
            return conn.execute(sql, params).fetchall()

    def test_three_bots_racing_for_same_coin_only_one_reservation(self):
        jobs = [("daily", "a" * 32), ("intraday", "b" * 32),
                ("aggressive", "c" * 32)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(record, bot, "SOL", nonce)
                       for bot, nonce in jobs]
            outcomes = [future.result(timeout=8) for future in futures]
        self.assertEqual(sum(int(row[0]) for row in outcomes), 1)
        self.assertTrue(all(row[2] in (
            "persisted-review-only-HOLD", "active-scope-held"
        ) for row in outcomes))
        rows = self.query(
            "select bot,state,fence,request_nonce from "
            "sender_review_ci.review_intents"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "review_only")
        self.assertEqual(rows[0][2], 1)
        self.assertEqual(len(self.query(
            "select 1 from sender_review_ci.review_events"
        )), 1)

    def test_same_nonce_cannot_replay_across_coins_or_bots(self):
        self.assertTrue(record()[0])
        self.assertFalse(record("intraday", "AVAX", "a" * 32)[0])
        self.assertFalse(record("aggressive", "SOL", "a" * 32)[0])
        self.assertEqual(len(self.query(
            "select 1 from sender_review_ci.review_intents"
        )), 1)

    def test_concurrent_account_wide_nonce_replay_is_not_stored_twice(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(record, "daily", "SOL", "f" * 32),
                pool.submit(record, "intraday", "AVAX", "f" * 32),
            ]
            answers = [f.result(timeout=8) for f in futures]
        self.assertEqual(sum(int(a[0]) for a in answers), 1)
        self.assertEqual(len(self.query(
            "select coin from sender_review_ci.review_intents"
        )), 1)

    def test_uncertain_ack_persists_hold_and_survives_new_connection(self):
        accepted = record()
        self.assertTrue(accepted[0])
        self.assertEqual(accepted[1], 1)
        with connect() as conn:
            held = conn.execute(
                "select sender_review_ci.hold_uncertain(%s,%s,%s,%s)",
                (ACCOUNT, "SOL", "a" * 32, 1),
            ).fetchone()[0]
        self.assertTrue(held)
        self.assertEqual(self.query(
            "select state from sender_review_ci.review_intents"
        ), [("hold_unknown",)])
        self.assertFalse(record("intraday", "SOL", "b" * 32)[0])
        self.assertFalse(record("daily", "SOL", "a" * 32)[0])
        self.assertEqual(self.query(
            "select kind from sender_review_ci.review_events order by event_id"
        ), [("review_recorded",), ("unknown_held",)])
        self.assertEqual(self.query(
            "select fence,active_nonce from sender_review_ci.scope_fences"
        ), [(1, "a" * 32)])

    def test_concurrent_uncertain_ack_transitions_are_single_event_and_hold(self):
        # Three competing recovery attempts use separate disposable DB
        # connections. The journal must never duplicate the unknown ACK
        # event or free the active fence even after clients disconnect.
        first = record(bot="aggressive", coin="SOL", nonce="d" * 32)
        self.assertTrue(first[0])
        self.assertEqual(first[1], 1)

        def hold_from_fresh_connection(_attempt):
            with connect() as conn:
                return conn.execute(
                    "select sender_review_ci.hold_uncertain(%s,%s,%s,%s)",
                    (ACCOUNT, "SOL", "d" * 32, 1),
                ).fetchone()[0]

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(hold_from_fresh_connection, range(3)))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 2)
        self.assertEqual(self.query(
            "SELECT kind FROM sender_review_ci.review_events "
            "ORDER BY event_id"
        ), [("review_recorded",), ("unknown_held",)])
        self.assertEqual(self.query(
            "SELECT state,bot,fence FROM sender_review_ci.review_intents"
        ), [("hold_unknown", "aggressive", 1)])
        self.assertEqual(self.query(
            "SELECT active_nonce,fence FROM sender_review_ci.scope_fences"
        ), [("d" * 32, 1)])
        self.assertFalse(hold_from_fresh_connection("later"))
        self.assertFalse(record("daily", "SOL", "e" * 32)[0])
        self.assertFalse(record("intraday", "SOL", "f" * 32)[0])
        self.assertEqual(len(self.query(
            "SELECT 1 FROM sender_review_ci.review_events"
        )), 2)

    def test_wrong_fence_nonce_or_scope_cannot_transition(self):
        self.assertTrue(record()[0])
        for account, coin, nonce, fence in (
            (ACCOUNT, "SOL", "b" * 32, 1),
            (ACCOUNT, "AVAX", "a" * 32, 1),
            (ACCOUNT, "SOL", "a" * 32, 2),
            ("0x" + "2" * 40, "SOL", "a" * 32, 1),
        ):
            with self.subTest(coin=coin, fence=fence):
                with connect() as conn:
                    result = conn.execute(
                        "select sender_review_ci.hold_uncertain(%s,%s,%s,%s)",
                        (account, coin, nonce, fence),
                    ).fetchone()[0]
                self.assertFalse(result)
        self.assertEqual(self.query(
            "select state from sender_review_ci.review_intents"
        ), [("review_only",)])

    def test_invalid_entries_never_create_fence(self):
        bad = [
            {"bot": "manual"},
            {"coin": "sol"},
            {"action": "close"},
            {"action": "pyramid_long"},
            {"action": "open_short", "side": "long"},
            {"size": "-0.5"},
            {"size": "0"},
            {"leverage": 100},
            {"nonce": "g" * 32},
        ]
        for data in bad:
            with self.subTest(data=data):
                params = dict(bot="daily", coin="SOL", nonce="a" * 32,
                              action="open_long", side="long",
                              size="0.16", leverage=2)
                params.update(data)
                answer = record(**params)
                self.assertFalse(answer[0])
        self.assertEqual(self.query(
            "select 1 from sender_review_ci.scope_fences"
        ), [])

    def test_killed_worker_after_committed_review_cannot_release_fence(self):
        # Crash an isolated child after DB commit, not a running bot.
        # Parent connection must observe durable active review lock.
        child = """
from sender_review.test_ci_journal_postgres import record
import os,sys,time
result=record(bot="aggressive",coin="SOL",nonce="e"*32)
assert result[0], result
print("RECORDED", flush=True)
time.sleep(30)
"""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT)
        worker = subprocess.Popen(
            [sys.executable, "-c", child],
            cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(worker.stdout.readline().strip(), "RECORDED")
            worker.kill()
            worker.communicate(timeout=5)
            self.assertNotEqual(worker.returncode, 0)
            self.assertFalse(record("daily", "SOL", "f" * 32)[0])
            self.assertEqual(self.query(
                "select bot,state,fence from sender_review_ci.review_intents"
            ), [("aggressive", "review_only", 1)])
            self.assertEqual(self.query(
                "select active_nonce from sender_review_ci.scope_fences"
            ), [("e" * 32,)])
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=5)

    def test_killed_transaction_does_not_claim_committed_intent(self):
        # Force a child to hold an uncommitted DB scope lock. Terminating
        # this disposable worker must roll back its review-only mutation.
        child = """
import os,psycopg,sys,time
conn=psycopg.connect(host="127.0.0.1",port=5432,
    dbname="sender_review_test",user="postgres",
    password=os.environ["PGPASSWORD"])
conn.execute("insert into sender_review_ci.scope_fences"
    "(environment,account,dex,coin,fence,active_nonce)"
    " values ('testnet',%s,'','SOL',1,%s)",
    ("0x"+"1"*40,"f"*32))
print("UNCOMMITTED", flush=True)
time.sleep(30)
"""
        worker = subprocess.Popen(
            [sys.executable, "-c", child],
            cwd=str(ROOT), env=dict(os.environ),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(worker.stdout.readline().strip(), "UNCOMMITTED")
            worker.kill()
            worker.communicate(timeout=5)
            self.assertNotEqual(worker.returncode, 0)
            self.assertEqual(self.query(
                "select 1 from sender_review_ci.scope_fences"
            ), [])
            # With no committed intent, a new independent review can record
            # a request. No exchange sends are possible in these tests.
            self.assertTrue(record("intraday", "SOL", "a" * 32)[0])
            self.assertEqual(len(self.query(
                "select 1 from sender_review_ci.review_intents"
            )), 1)
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=5)

    def test_interrupted_unknown_ack_transaction_rolls_back_without_releasing_fence(self):
        # A disposable child connection is killed before COMMIT in two
        # phases: after the state UPDATE, or after the review-only
        # hold_uncertain() routine returned (which inserts an event).
        # Neither uncommitted transition may survive a disconnected worker.
        self.assertTrue(record(bot="intraday", coin="SOL", nonce="7" * 32)[0])
        child = """
import os, psycopg, sys, time
account = "0x" + "1" * 40
conn = psycopg.connect(
    host="127.0.0.1", port=5432, dbname="sender_review_test",
    user="postgres", password=os.environ["PGPASSWORD"],
)
if sys.argv[1] == "after_state_update":
    changed = conn.execute(
        "UPDATE sender_review_ci.review_intents SET state='hold_unknown' "
        "WHERE environment='testnet' AND account=%s AND coin='SOL' "
        "AND request_nonce=%s AND fence=1 AND state='review_only' "
        "RETURNING id", (account, "7" * 32)
    ).fetchone()
    assert changed is not None
else:
    changed = conn.execute(
        "SELECT sender_review_ci.hold_uncertain(%s,%s,%s,%s)",
        (account, "SOL", "7" * 32, 1),
    ).fetchone()
    assert changed == (True,)
print("RECOVERY_UNCOMMITTED", flush=True)
time.sleep(30)
"""
        for phase in ("after_state_update", "after_hold_function"):
            with self.subTest(phase=phase):
                worker = subprocess.Popen(
                    [sys.executable, "-c", child, phase],
                    cwd=str(ROOT), env=dict(os.environ),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True,
                )
                try:
                    self.assertEqual(
                        worker.stdout.readline().strip(), "RECOVERY_UNCOMMITTED"
                    )
                    worker.kill()
                    worker.communicate(timeout=5)
                    self.assertNotEqual(worker.returncode, 0)
                    self.assertEqual(self.query(
                        "SELECT state FROM sender_review_ci.review_intents"
                    ), [("review_only",)])
                    self.assertEqual(self.query(
                        "SELECT kind FROM sender_review_ci.review_events "
                        "ORDER BY event_id"
                    ), [("review_recorded",)])
                    self.assertEqual(self.query(
                        "SELECT active_nonce,fence "
                        "FROM sender_review_ci.scope_fences"
                    ), [("7" * 32, 1)])
                    self.assertFalse(record(
                        bot="daily", coin="SOL", nonce="8" * 32
                    )[0])
                finally:
                    if worker.poll() is None:
                        worker.kill()
                        worker.communicate(timeout=5)
        # An independently retried recovery can record one durable HOLD,
        # but must never authorize another entry or clear the same fence.
        with connect() as conn:
            self.assertTrue(conn.execute(
                "SELECT sender_review_ci.hold_uncertain(%s,%s,%s,%s)",
                (ACCOUNT, "SOL", "7" * 32, 1),
            ).fetchone()[0])
        self.assertEqual(self.query(
            "SELECT state FROM sender_review_ci.review_intents"
        ), [("hold_unknown",)])
        self.assertEqual(self.query(
            "SELECT kind FROM sender_review_ci.review_events "
            "ORDER BY event_id"
        ), [("review_recorded",), ("unknown_held",)])
        self.assertFalse(record(
            bot="aggressive", coin="SOL", nonce="9" * 32
        )[0])

    def test_fresh_worker_after_unknown_ack_cannot_replay_or_release_lock(self):
        # Simulate restart by exiting the original client, then launching
        # a separate Python interpreter against the same disposable DB.
        # No service, exchange request or signer is involved.
        first = record(bot="daily", coin="SOL", nonce="a" * 32)
        self.assertTrue(first[0])
        with connect() as conn:
            self.assertTrue(conn.execute(
                "SELECT sender_review_ci.hold_uncertain(%s,%s,%s,%s)",
                (ACCOUNT, "SOL", "a" * 32, 1),
            ).fetchone()[0])
        before = self.query(
            "SELECT bot,coin,request_nonce,state,fence "
            "FROM sender_review_ci.review_intents"
        )
        events_before = self.query(
            "SELECT kind FROM sender_review_ci.review_events "
            "ORDER BY event_id"
        )
        self.assertEqual(events_before, [
            ("review_recorded",), ("unknown_held",),
        ])
        child = """
import json
import os
import sys
if (os.environ.get("SENDER_REVIEW_DISPOSABLE_CI") != "1"
        or os.environ.get("PGDATABASE") != "sender_review_test"
        or os.environ.get("PGHOST") != "127.0.0.1"):
    raise SystemExit("disposable CI only")
from sender_review.test_ci_journal_postgres import connect, record
attempts = (
    ("daily", "SOL", "a" * 32),
    ("intraday", "SOL", "b" * 32),
    ("aggressive", "SOL", "c" * 32),
    ("intraday", "AVAX", "a" * 32),
)
results = [record(bot=bot, coin=coin, nonce=nonce)[0]
           for bot, coin, nonce in attempts]
with connect() as conn:
    repeat_hold = conn.execute(
        "SELECT sender_review_ci.hold_uncertain(%s,%s,%s,%s)",
        ("0x" + "1" * 40, "SOL", "a" * 32, 1),
    ).fetchone()[0]
print(json.dumps({"claims": results, "repeated_hold": repeat_hold}))
"""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT)
        restarted = subprocess.run(
            [sys.executable, "-c", child], cwd=str(ROOT),
            env=env, capture_output=True, text=True, timeout=15,
            check=True,
        )
        import json
        result = json.loads(restarted.stdout)
        self.assertEqual(result, {
            "claims": [False, False, False, False],
            "repeated_hold": False,
        })
        self.assertEqual(self.query(
            "SELECT bot,coin,request_nonce,state,fence "
            "FROM sender_review_ci.review_intents"
        ), before)
        self.assertEqual(self.query(
            "SELECT kind FROM sender_review_ci.review_events "
            "ORDER BY event_id"
        ), events_before)
        self.assertEqual(self.query(
            "SELECT active_nonce,fence FROM sender_review_ci.scope_fences "
            "WHERE coin='SOL'"
        ), [("a" * 32, 1)])
        # record_review_only may create an unclaimed empty scope row
        # before detecting account-wide nonce replay. It must NOT
        # install an active AVAX fence or create another intent.
        self.assertEqual(self.query(
            "SELECT fence,active_nonce FROM sender_review_ci.scope_fences "
            "WHERE coin='AVAX'"
        ), [(0, None)])

    def test_review_events_are_append_only_during_uncertain_ack(self):
        # Review-only journal events must not be editable to erase a HOLD
        # after a simulated unknown-ACK recovery. No exchange operation.
        self.assertTrue(record(bot="daily", coin="SOL", nonce="a" * 32)[0])
        with connect() as conn:
            held = conn.execute(
                "select sender_review_ci.hold_uncertain(%s,%s,%s,%s)",
                (ACCOUNT, "SOL", "a" * 32, 1),
            ).fetchone()[0]
        self.assertTrue(held)
        before = self.query(
            "SELECT event_id,intent_id,kind FROM "
            "sender_review_ci.review_events ORDER BY event_id"
        )
        self.assertEqual([row[2] for row in before],
                         ["review_recorded", "unknown_held"])
        for statement in (
            "UPDATE sender_review_ci.review_events "
            "SET kind='review_recorded' WHERE kind='unknown_held'",
            "DELETE FROM sender_review_ci.review_events "
            "WHERE kind='unknown_held'",
            "UPDATE sender_review_ci.review_events "
            "SET created_at=clock_timestamp() "
            "WHERE kind='review_recorded'",
            "DELETE FROM sender_review_ci.review_events "
            "WHERE kind='review_recorded'",
        ):
            with self.subTest(statement=statement):
                with connect() as conn:
                    with self.assertRaises(psycopg.errors.RaiseException):
                        conn.execute(statement)
                self.assertEqual(self.query(
                    "SELECT event_id,intent_id,kind FROM "
                    "sender_review_ci.review_events ORDER BY event_id"
                ), before)
        self.assertEqual(self.query(
            "SELECT state FROM sender_review_ci.review_intents"
        ), [("hold_unknown",)])

    def test_no_release_send_or_trade_function_exists(self):
        routines = self.query(
            "select proname from pg_proc p join pg_namespace n "
            "on n.oid=p.pronamespace where n.nspname='sender_review_ci'"
        )
        self.assertEqual(
            {item[0] for item in routines},
            {"record_review_only", "hold_uncertain", "reject_fixture_evidence_mutation"},
        )
        states = self.query(
            "select distinct state from sender_review_ci.review_intents"
        )
        self.assertEqual(states, [])


if __name__ == "__main__":
    unittest.main()
