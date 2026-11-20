"""Disposable Postgres integration of original three-bot trade decisions.

The tests use isolated safety_test PostgreSQL 16 with synthetic accounts.
They never import original executors or Hyperliquid, or create live orders.
"""
import concurrent.futures
import os
import unittest
import uuid

import psycopg

from offline_original_bot_postgres_bridge_ci import record_offline_original_entry

ACCOUNT = "0x" + "1" * 40
BOTS = ("daily", "intraday", "aggressive")


@unittest.skipUnless(
    os.environ.get("ISOLATED_POSTGRES_CI") == "1"
    and os.environ.get("PGDATABASE") == "safety_test",
    "requires disposable safety_test PostgreSQL",
)
class OriginalBotPostgresBridgeTests(unittest.TestCase):
    @staticmethod
    def admin():
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True,
        )

    @staticmethod
    def factory(bot):
        def connect():
            return psycopg.connect(
                host="localhost", port=5432, dbname="safety_test",
                user="entry_login_" + bot,
                password="disposable-" + bot + "-only",
            )
        return connect

    def setUp(self):
        with self.admin() as db:
            db.execute(
                "truncate public.ci_scoped_entry_intents, "
                "public.ci_scoped_entry_claims"
            )

    def request(self, bot="daily", action="open_long", side="long",
                coin="SOL", size="0.025", factory_bot=None):
        return record_offline_original_entry(
            connection_factory=self.factory(factory_bot or bot),
            verified_bot=bot,
            trade={"action": action, "side": side, "hl_coin": coin},
            rounded_size=size, pinned_environment="mainnet",
            pinned_account=ACCOUNT,
        )

    def test_each_original_bot_can_record_synthetic_entry(self):
        for bot, coin, side, action in (
            ("daily", "SOL", "long", "open_long"),
            ("intraday", "AVAX", "short", "open_short"),
            ("aggressive", "LINK", "long", "open_long"),
        ):
            with self.subTest(bot=bot):
                decision=self.request(bot, action, side, coin)
                self.assertEqual(decision.state, "reserved_offline_only")
                self.assertIsNotNone(decision.intent_id)
                self.assertGreater(decision.fence, 0)
                self.assertFalse(decision.submit_authorized)
                with self.admin() as db:
                    row=db.execute(
                        "select bot,action,requested_size,status "
                        "from public.ci_scoped_entry_intents where coin=%s",
                        (coin,),
                    ).fetchone()
                self.assertEqual(row[0:2],(bot,action))
                self.assertEqual(str(row[2]),"0.025")
                self.assertEqual(row[3],"pending")

    def test_three_bots_same_coin_one_reservation_no_dispatch(self):
        def attempt(bot):
            return self.request(bot=bot)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            decisions=list(pool.map(attempt,BOTS))
        self.assertEqual(
            sum(d.state=="reserved_offline_only" for d in decisions),1,
            decisions,
        )
        self.assertEqual(sum(d.state=="hold" for d in decisions),2)
        self.assertTrue(all(not d.submit_authorized for d in decisions))
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_claims"
            ).fetchone()[0],1)
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_intents"
            ).fetchone()[0],1)

    def test_second_bot_cannot_override_owner_or_replay(self):
        first=self.request("daily")
        self.assertEqual(first.state,"reserved_offline_only")
        self.assertEqual(self.request("daily").state,"hold")
        self.assertEqual(self.request("intraday").state,"hold")
        with self.admin() as db:
            row=db.execute(
                "select bot,token from public.ci_scoped_entry_claims"
            ).fetchone()
        self.assertEqual(row,("daily",uuid.UUID(first.intent_id)))

    def test_login_impersonation_holds_and_keeps_tables_empty(self):
        for bot in BOTS:
            wrong=next(x for x in BOTS if x!=bot)
            with self.subTest(bot=bot):
                self.assertEqual(
                    self.request(bot=bot, factory_bot=wrong).state,"hold"
                )
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_claims"
            ).fetchone()[0],0)

    def test_unsupported_actions_and_bad_sizes_never_record(self):
        for action,side in (
            ("close","long"),("pyramid_long","long"),
            ("pyramid_short","short"),("open_short","long"),
        ):
            with self.subTest(action=action):
                self.assertEqual(
                    self.request(action=action,side=side).state,"hold")
        for size in ("0","NaN","Infinity","-1","1e5",0.25):
            with self.subTest(size=size):
                self.assertEqual(self.request(size=size).state,"hold")
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_intents"
            ).fetchone()[0],0)

    def test_guard_denies_non_ci_environment_before_opening_database(self):
        old=os.environ.pop("ISOLATED_POSTGRES_CI")
        opened=[]
        try:
            def fail_if_opened():
                opened.append(True)
                raise AssertionError("must not connect")
            decision=record_offline_original_entry(
                connection_factory=fail_if_opened, verified_bot="daily",
                trade={"action":"open_long","side":"long","hl_coin":"SOL"},
                rounded_size="0.025",pinned_environment="mainnet",
                pinned_account=ACCOUNT,
            )
            self.assertEqual(decision.state,"hold")
            self.assertFalse(opened)
        finally:
            os.environ["ISOLATED_POSTGRES_CI"]=old


if __name__=="__main__":
    unittest.main()
