"""Real OS-process crash tests for disposable PostgreSQL fake sender only.

An intentional os._exit(81/82) simulates loss of sender process while a
synthetic order attempt is being journaled. No Hyperliquid API, signer,
credential, production database, or live bot is imported.
"""
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid

import psycopg

from offline_ci_pg_fake_sender import simulate_postgres_fake_dispatch_once
from offline_shared_sender_prototype import FakeExchange

ACCOUNT = "0x" + "1" * 40

CHILD = """
import json,os,sys,uuid
import psycopg
from offline_ci_pg_fake_sender import simulate_postgres_fake_dispatch_once
from offline_shared_sender_prototype import FakeExchange

mode,token_text,fence_text,evidence_path=sys.argv[1:5]
token=uuid.UUID(token_text)
fence=int(fence_text)

def sender():
    return psycopg.connect(
        host='localhost',port=5432,dbname='safety_test',
        user='ci_sender_worker',password='disposable-sender-only')

if mode=='before_commit':
    # The SQL function writes a marker in an OPEN transaction. Crash
    # before committing: PostgreSQL must roll it back.
    conn=sender()
    row=conn.execute(
        'select marked,stored_cloid from public.ci_sender_mark_unknown(%s,%s)',
        (token,fence)).fetchone()
    assert row[0] is True,row
    os._exit(81)
elif mode=='after_fake':
    fake=FakeExchange()
    def record_and_die(token,cloid):
        # Durable fixture-only evidence simulates an external fake effect.
        with open(evidence_path,'w',encoding='utf-8') as out:
            out.write(token+' '+cloid)
            out.flush()
            os.fsync(out.fileno())
        os._exit(82)
    fake.record_fake_attempt=record_and_die
    simulate_postgres_fake_dispatch_once(
        sender_connection_factory=sender,token=token,fence=fence,fake=fake)
    os._exit(99)
elif mode=='retry':
    fake=FakeExchange()
    result=simulate_postgres_fake_dispatch_once(
        sender_connection_factory=sender,token=token,fence=fence,fake=fake)
    print(json.dumps({
        'state':result.state,'attempts':len(fake.attempts),
        'submit_authorized':result.submit_authorized,
    }),flush=True)
else:
    os._exit(98)
"""


@unittest.skipUnless(
    os.environ.get("ISOLATED_POSTGRES_CI") == "1"
    and os.environ.get("PGDATABASE") == "safety_test",
    "requires disposable PostgreSQL safety_test only",
)
class PgFakeSenderProcessCrashTests(unittest.TestCase):
    def admin(self):
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True,
        )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.evidence_path = os.path.join(
            self.temp.name, "synthetic-fake-effect.txt",
        )
        with self.admin() as db:
            db.execute(
                "truncate public.ci_sender_attempts, "
                "public.ci_sender_intents restart identity"
            )
        with psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="entry_login_daily", password="disposable-daily-only",
        ) as db:
            accepted, self.token, self.fence = db.execute(
                "select accepted,intent_id,fencing "
                "from public.ci_sender_reserve(%s,%s,%s,%s,%s,%s,%s,%s)",
                ("mainnet", ACCOUNT, "", "SOL", "daily",
                 "open_long", "0.025", uuid.uuid4()),
            ).fetchone()
        self.assertTrue(accepted)

    def child(self, mode):
        return subprocess.run(
            [sys.executable, "-c", CHILD, mode, str(self.token),
             str(self.fence), self.evidence_path],
            timeout=15, capture_output=True, text=True, check=False,
        )

    def saved(self):
        with self.admin() as db:
            return db.execute(
                "select i.state,i.cloid,a.intent_token,a.fence_token,a.cloid "
                "from public.ci_sender_intents i "
                "left join public.ci_sender_attempts a "
                "on a.intent_token=i.token"
            ).fetchone()

    def test_crash_before_marker_commit_rolls_back_then_one_fake_send(self):
        child = self.child("before_commit")
        self.assertEqual(child.returncode, 81, child.stderr)
        original = self.saved()
        self.assertEqual(original[0], "reserved")
        self.assertEqual(original[2:], (None, None, None))
        self.assertFalse(os.path.exists(self.evidence_path))

        def sender():
            return psycopg.connect(
                host="localhost", port=5432, dbname="safety_test",
                user="ci_sender_worker", password="disposable-sender-only",
            )

        fake = FakeExchange()
        decision = simulate_postgres_fake_dispatch_once(
            sender_connection_factory=sender, token=self.token,
            fence=self.fence, fake=fake,
        )
        self.assertEqual(decision.state, "observed_unverified")
        self.assertFalse(decision.submit_authorized)
        self.assertEqual(fake.attempts, [(str(self.token), original[1])])
        committed = self.saved()
        self.assertEqual(committed[0], "dispatch_unknown")
        self.assertEqual(committed[2:], (self.token, self.fence, original[1]))
        retry = self.child("retry")
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertEqual(json.loads(retry.stdout), {
            "state": "hold", "attempts": 0, "submit_authorized": False,
        })

    def test_crash_after_fake_effect_before_ack_blocks_parallel_restarts(self):
        original_cloid = self.saved()[1]
        child = self.child("after_fake")
        self.assertEqual(child.returncode, 82, child.stderr)
        with open(self.evidence_path, encoding="utf-8") as record:
            self.assertEqual(
                record.read(), str(self.token) + " " + original_cloid,
            )
        committed = self.saved()
        self.assertEqual(committed, (
            "dispatch_unknown", original_cloid, self.token,
            self.fence, original_cloid,
        ))

        # Separate Python processes compete after the original fake
        # side effect was recorded. No fresh simulated send is permitted.
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            restarted = list(pool.map(
                lambda _: self.child("retry"), range(6),
            ))
        for proc in restarted:
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout), {
                "state": "hold", "attempts": 0,
                "submit_authorized": False,
            })
        self.assertEqual(self.saved(), committed)
        with open(self.evidence_path, encoding="utf-8") as record:
            self.assertEqual(
                record.read(), str(self.token) + " " + original_cloid,
            )


if __name__ == "__main__":
    unittest.main()
