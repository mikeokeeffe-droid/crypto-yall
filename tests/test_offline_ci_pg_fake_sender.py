"""PostgreSQL durable-marker-before-fake tests in disposable safety_test.

No production credentials, order SDK, exchange network or trade execution.
"""
import concurrent.futures
import os
import uuid
import unittest

import psycopg

from offline_ci_pg_fake_sender import simulate_postgres_fake_dispatch_once
from offline_shared_sender_prototype import FakeExchange

ACCOUNT = "0x" + "1" * 40


@unittest.skipUnless(
    os.environ.get("ISOLATED_POSTGRES_CI") == "1"
    and os.environ.get("PGDATABASE") == "safety_test",
    "only disposable PostgreSQL CI",
)
class PostgreSQLFakeSenderTests(unittest.TestCase):
    def admin(self):
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True,
        )

    @staticmethod
    def sender():
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="ci_sender_worker", password="disposable-sender-only",
        )

    def setUp(self):
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
        self.fake = FakeExchange()

    def attempt(self, **overrides):
        args = dict(
            sender_connection_factory=self.sender,
            token=self.token, fence=self.fence, fake=self.fake,
        )
        args.update(overrides)
        return simulate_postgres_fake_dispatch_once(**args)

    def journal(self):
        with self.admin() as db:
            return db.execute(
                "select i.state,i.cloid,a.intent_token,a.fence_token,a.cloid "
                "from public.ci_sender_intents i "
                "left join public.ci_sender_attempts a on a.intent_token=i.token"
            ).fetchone()

    def test_marker_commits_before_fake_observes(self):
        original = self.fake.record_fake_attempt
        evidence = []

        def callback(token, cloid):
            evidence.append(self.journal())
            return original(token, cloid)

        self.fake.record_fake_attempt = callback
        result = self.attempt()
        self.assertEqual(result.state, "observed_unverified")
        self.assertFalse(result.submit_authorized)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0][0], "dispatch_unknown")
        self.assertEqual(evidence[0][1], evidence[0][4])
        self.assertEqual(evidence[0][2], self.token)
        self.assertEqual(evidence[0][3], self.fence)
        self.assertEqual(len(self.fake.attempts), 1)

    def test_parallel_restarted_sender_logins_make_only_one_fake_attempt(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            decisions = list(pool.map(lambda _: self.attempt(), range(12)))
        self.assertEqual(
            sum(item.state == "observed_unverified" for item in decisions),
            1, decisions,
        )
        self.assertEqual(len(self.fake.attempts), 1)
        self.assertTrue(all(not d.submit_authorized for d in decisions))
        self.assertEqual(self.journal()[0], "dispatch_unknown")
        self.assertEqual(self.attempt().state, "hold")

    def test_fake_accepts_but_reply_lost_cannot_replay(self):
        def lost_reply(token, cloid):
            self.fake.attempts.append((token, cloid))
            raise TimeoutError("synthetic exchange response lost")

        self.fake.record_fake_attempt = lost_reply
        self.assertEqual(self.attempt().state, "hold")
        self.assertEqual(len(self.fake.attempts), 1)
        self.assertEqual(self.attempt().state, "hold")
        self.assertEqual(len(self.fake.attempts), 1)
        self.assertEqual(self.journal()[0], "dispatch_unknown")

    def test_precommitted_marker_survives_crash_before_fake(self):
        with self.sender() as db:
            self.assertTrue(db.execute(
                "select marked from public.ci_sender_mark_unknown(%s,%s)",
                (self.token, self.fence),
            ).fetchone()[0])
        self.assertEqual(self.journal()[0], "dispatch_unknown")
        self.assertEqual(self.attempt().state, "hold")
        self.assertEqual(self.fake.attempts, [])

    def test_stale_claim_or_bad_sender_identity_does_not_touch_journal(self):
        for change in (
            {"token": uuid.uuid4()},
            {"fence": self.fence + 1},
            {"token": str(self.token)},
            {"fake": object()},
            {"sender_connection_factory": lambda: psycopg.connect(
                host="localhost", port=5432, dbname="safety_test",
                user="entry_login_daily", password="disposable-daily-only",
            )},
        ):
            with self.subTest(change=list(change)):
                self.assertEqual(self.attempt(**change).state, "hold")
        self.assertEqual(self.journal(), (
            "reserved", self.journal()[1], None, None, None,
        ))
        self.assertEqual(self.fake.attempts, [])

    def test_rollback_before_commit_preserves_unattempted_intent(self):
        def commit_failure():
            db = self.sender()
            # Caller sees a DB exception when committing. The exact reason
            # might be a lost acknowledgement; no fake callback is permitted.
            class AbortCommit:
                def __enter__(self):
                    return db.__enter__()
                def __exit__(self, typ, value, trace):
                    db.rollback()
                    db.close()
                    raise OSError("synthetic DB commit acknowledgement lost")
            return AbortCommit()

        self.assertEqual(self.attempt(sender_connection_factory=commit_failure).state,
                         "hold")
        self.assertEqual(self.fake.attempts, [])
        self.assertEqual(self.journal()[0], "reserved")
        self.assertIsNone(self.journal()[2])


if __name__ == "__main__":
    unittest.main()
