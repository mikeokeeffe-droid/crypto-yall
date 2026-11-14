"""Disposable PostgreSQL V2 leverage-bound review journal regression checks.

No signing keys, Hyperliquid SDK, order dispatch, close, testnet connection
or production DB. This is NOT evidence of actual leverage being applied.
"""
import concurrent.futures
import os
import unittest
import uuid

import psycopg
from psycopg.errors import InsufficientPrivilege

ACCOUNT = "0x" + "1" * 40
BOTS = ("daily", "intraday", "aggressive")


@unittest.skipUnless(
    os.environ.get("ISOLATED_POSTGRES_CI") == "1"
    and os.environ.get("PGDATABASE") == "safety_test",
    "requires disposable PostgreSQL safety_test",
)
class SenderV2LeverageReviewTests(unittest.TestCase):
    @staticmethod
    def connect(user):
        password = (
            "postgres" if user == "postgres"
            else "disposable-sender-only" if user == "ci_sender_worker"
            else "disposable-reviewer-only" if user == "ci_sender_reviewer"
            else "disposable-" + user.removeprefix("entry_login_") + "-only"
        )
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user=user, password=password, autocommit=True,
        )

    def setUp(self):
        with self.connect("postgres") as conn:
            conn.execute("truncate public.ci_sender_v2_reviews restart identity")

    @staticmethod
    def args(bot="daily", coin="SOL", leverage=2):
        return ("mainnet", ACCOUNT, "", coin, bot,
                "open_long", "0.025", leverage, "cross", uuid.uuid4())

    def record(self, bot="daily", *overrides):
        data = overrides[0] if overrides else self.args(bot)
        with self.connect("entry_login_" + bot) as conn:
            return conn.execute(
                "select recorded,review_token,fencing "
                "from public.ci_sender_v2_record_review("
                "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", data,
            ).fetchone()

    def rows(self):
        with self.connect("postgres") as conn:
            return conn.execute(
                "select bot,action,requested_size,requested_leverage,"
                "margin_mode,state,cloid,token,fence_token "
                "from public.ci_sender_v2_reviews order by coin"
            ).fetchall()

    def test_three_bots_compete_with_size_and_leverage_immutably_bound(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda b: self.record(b), BOTS))
        accepted = [r for r in results if r[0] is True]
        self.assertEqual(len(accepted), 1, results)
        self.assertEqual(sum(r[0] is False for r in results), 2)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertIn(rows[0][0], BOTS)
        self.assertEqual(rows[0][1], "open_long")
        self.assertEqual(str(rows[0][2]), "0.025")
        self.assertEqual(rows[0][3:6], (2, "cross", "review_only"))
        self.assertRegex(rows[0][6], r"^0x[0-9a-f]{32}$")
        self.assertEqual(rows[0][7:9], accepted[0][1:3])
        self.assertEqual(self.record("daily"), (False, None, None))
        self.assertEqual(self.rows(), rows)

    def test_review_is_not_an_order_and_sender_has_no_review_write_rights(self):
        result = self.record()
        self.assertTrue(result[0])
        for user in (*("entry_login_" + b for b in BOTS),
                     "ci_sender_worker"):
            with self.subTest(user=user), self.connect(user) as conn:
                with self.assertRaises(InsufficientPrivilege):
                    conn.execute("select * from public.ci_sender_v2_reviews")
                with self.assertRaises(InsufficientPrivilege):
                    conn.execute("update public.ci_sender_v2_reviews "
                                 "set requested_leverage=3")
                with self.assertRaises(InsufficientPrivilege):
                    conn.execute("delete from public.ci_sender_v2_reviews")
        with self.connect("ci_sender_worker") as conn:
            with self.assertRaises(InsufficientPrivilege):
                conn.execute(
                    "select * from public.ci_sender_v2_record_review("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", self.args())
        with self.connect("ci_sender_reviewer") as conn:
            evidence = conn.execute(
                "select bot,requested_size,requested_leverage,state "
                "from public.ci_sender_v2_reviews"
            ).fetchone()
            self.assertEqual(evidence[0], "daily")
            self.assertEqual(evidence[2:], (2, "review_only"))
            with self.assertRaises(InsufficientPrivilege):
                conn.execute("delete from public.ci_sender_v2_reviews")
        self.assertEqual(self.rows()[0][5], "review_only")

    def test_invalid_or_spoofed_leverage_review_is_rejected(self):
        base = list(self.args())
        cases = {
            "zero_leverage": {7: 0},
            "too_high": {7: 6},
            "no_leverage": {7: None},
            "wrong_margin_mode": {8: "isolated"},
            "wrong_bot": {4: "aggressive"},
            "wrong_account": {1: "0x" + "2" * 40},
            "wrong_environment": {0: "unknown"},
            "negative_quantity": {6: "-1"},
            "unknown_action": {5: "pyramid_long"},
        }
        for name, changes in cases.items():
            with self.subTest(name=name):
                args = list(base)
                for index, value in changes.items():
                    args[index] = value
                with self.connect("entry_login_daily") as conn:
                    with self.assertRaises(InsufficientPrivilege):
                        conn.execute(
                            "select * from public.ci_sender_v2_record_review("
                            "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", args)
        self.assertEqual(self.rows(), [])

    def test_request_id_and_existing_same_scope_cannot_replay(self):
        request = list(self.args())
        first = self.record("daily", request)
        self.assertTrue(first[0])
        another_coin = list(request)
        another_coin[3] = "AVAX"
        self.assertEqual(self.record("daily", another_coin),
                         (False, None, None))
        self.assertEqual(self.record("intraday"),
                         (False, None, None))
        self.assertEqual(len(self.rows()), 1)


if __name__ == "__main__":
    unittest.main()
