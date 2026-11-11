"""Isolated disposable PostgreSQL sender journal regression tests.

CI-only roles, synthetic account and fake recorder; no Hyperliquid SDK,
trading signer, secrets, order placement, or production database migration.
"""
import concurrent.futures
import os
import uuid
import unittest

import psycopg
from psycopg.errors import InsufficientPrivilege

ACCOUNT = "0x" + "1" * 40
BOTS = ("daily", "intraday", "aggressive")


@unittest.skipUnless(
    os.environ.get("ISOLATED_POSTGRES_CI") == "1"
    and os.environ.get("PGDATABASE") == "safety_test",
    "requires disposable PostgreSQL safety_test only",
)
class OfflineSenderJournalTests(unittest.TestCase):
    def admin(self):
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True,
        )

    def login(self, who):
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user=who, password=("disposable-" + who.removeprefix("entry_login_")
                                + "-only"),
            autocommit=True,
        )

    def setUp(self):
        with self.admin() as db:
            db.execute(
                "truncate public.ci_sender_attempts, "
                "public.ci_sender_intents restart identity"
            )

    def reserve(self, bot="daily", coin="SOL", action="open_long",
                size="0.025", request_id=None):
        with self.login("entry_login_" + bot) as db:
            return db.execute(
                "select accepted,intent_id,fencing "
                "from public.ci_sender_reserve(%s,%s,%s,%s,%s,%s,%s,%s)",
                ("mainnet", ACCOUNT, "", coin, bot, action,
                 size, request_id or uuid.uuid4()),
            ).fetchone()

    def mark(self, token, fence, *, who="ci_sender_worker"):
        with self.login(who) as db:
            return db.execute(
                "select marked,stored_cloid "
                "from public.ci_sender_mark_unknown(%s,%s)",
                (token, fence),
            ).fetchone()

    def test_three_bots_compete_and_commit_independent_cloid(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(self.reserve, BOTS))
        wins = [entry for entry in results if entry[0]]
        self.assertEqual(len(wins), 1, results)
        self.assertEqual(sum(not entry[0] for entry in results), 2)
        token, fence = wins[0][1:]
        with self.admin() as db:
            row = db.execute(
                "select token,fence_token,cloid,requested_size,bot,state "
                "from public.ci_sender_intents"
            ).fetchone()
        self.assertEqual(row[0], token)
        self.assertEqual(row[1], fence)
        self.assertRegex(row[2], r"^0x[0-9a-f]{32}$")
        self.assertEqual(str(row[3]), "0.025")
        self.assertEqual(row[5], "reserved")
        self.assertEqual(self.mark(token, fence), (True, row[2]))
        self.assertEqual(self.mark(token, fence), (False, None))
        with self.admin() as db:
            state = db.execute(
                "select i.state,a.intent_token,a.fence_token,a.cloid "
                "from public.ci_sender_intents i "
                "join public.ci_sender_attempts a on a.intent_token=i.token"
            ).fetchone()
        self.assertEqual(state, ("dispatch_unknown", token, fence, row[2]))

    def test_lost_ack_and_parallel_sender_restart_never_mark_twice(self):
        accepted, token, fence = self.reserve()
        self.assertTrue(accepted)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(
                lambda _: self.mark(token, fence), range(12),
            ))
        self.assertEqual(sum(entry[0] for entry in outcomes), 1, outcomes)
        self.assertEqual(sum(not entry[0] for entry in outcomes), 11)
        self.assertEqual(self.mark(token, fence), (False, None))
        self.assertEqual(self.reserve("intraday"), (False, None, None))
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_sender_attempts"
            ).fetchone()[0], 1)

    def test_uncommitted_marker_rolls_back_and_retry_can_mark_once(self):
        accepted, token, fence = self.reserve()
        self.assertTrue(accepted)
        with self.login("ci_sender_worker") as db:
            db.autocommit = False
            self.assertEqual(db.execute(
                "select marked,stored_cloid "
                "from public.ci_sender_mark_unknown(%s,%s)",
                (token, fence),
            ).fetchone()[0], True)
            db.rollback()
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select state from public.ci_sender_intents"
            ).fetchone()[0], "reserved")
            self.assertEqual(db.execute(
                "select count(*) from public.ci_sender_attempts"
            ).fetchone()[0], 0)
        self.assertTrue(self.mark(token, fence)[0])
        self.assertEqual(self.mark(token, fence), (False, None))

    def test_stale_fences_wrong_tokens_and_missing_claim_hold(self):
        accepted, token, fence = self.reserve()
        self.assertTrue(accepted)
        self.assertEqual(self.mark(uuid.uuid4(), fence), (False, None))
        self.assertEqual(self.mark(token, fence + 1), (False, None))
        self.assertEqual(self.mark(token, fence), (True,
                         self._cloid_for(token)))
        self.assertEqual(self.mark(token, fence), (False, None))

    def _cloid_for(self, token):
        with self.admin() as db:
            return db.execute(
                "select cloid from public.ci_sender_intents where token=%s",
                (token,),
            ).fetchone()[0]

    def test_bots_cannot_mark_or_modify_sender_journal(self):
        accepted, token, fence = self.reserve()
        self.assertTrue(accepted)
        for bot in BOTS:
            with self.subTest(bot=bot), self.login("entry_login_" + bot) as db:
                with self.assertRaises(InsufficientPrivilege):
                    db.execute(
                        "select * from public.ci_sender_mark_unknown(%s,%s)",
                        (token, fence),
                    )
                for table in ("public.ci_sender_attempts",
                              "public.ci_sender_intents"):
                    with self.subTest(table=table):
                        with self.assertRaises(InsufficientPrivilege):
                            db.execute("select * from " + table)
                        with self.assertRaises(InsufficientPrivilege):
                            db.execute("delete from " + table)
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_sender_attempts"
            ).fetchone()[0], 0)
            self.assertEqual(db.execute(
                "select state from public.ci_sender_intents"
            ).fetchone()[0], "reserved")

    def test_sender_cannot_reserve_or_directly_modify_claims(self):
        with self.login("ci_sender_worker") as db:
            with self.assertRaises(InsufficientPrivilege):
                db.execute(
                    "select * from public.ci_sender_reserve("
                    "%s,%s,%s,%s,%s,%s,%s,%s)",
                    ("mainnet", ACCOUNT, "", "SOL", "daily",
                     "open_long", "0.025", uuid.uuid4()),
                )
            with self.assertRaises(InsufficientPrivilege):
                db.execute("delete from public.ci_sender_intents")
            with self.assertRaises(InsufficientPrivilege):
                db.execute("delete from public.ci_sender_attempts")

    def test_invalid_or_replayed_request_cannot_create_second_claim(self):
        request_id = uuid.uuid4()
        first = self.reserve(request_id=request_id)
        self.assertTrue(first[0])
        self.assertEqual(self.reserve(coin="AVAX",
                                      request_id=request_id),
                         (False, None, None))
        self.assertEqual(self.reserve(bot="intraday"),
                         (False, None, None))
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_sender_intents"
            ).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
