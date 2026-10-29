"""Disposable PostgreSQL integration for all three authenticated executors."""
import concurrent.futures
import os
import secrets
import threading
import unittest
import uuid

import psycopg
from psycopg import sql

from authenticated_executor_integration_harness_staging import (
    execute_offline_authenticated_trade,
)
from test_real_executor_order_boundaries_offline import FILES, load_function
from test_trusted_executor_gateway_staging import (
    AUDIENCE,
    ISSUER,
    KEYS,
    signed_token,
)
from trusted_executor_gateway_staging import stage_entry_claim
from trusted_executor_postgres_transport_staging import restricted_executor_rpc


@unittest.skipUnless(os.getenv("ISOLATED_POSTGRES_CI") == "1",
                     "only run on disposable PostgreSQL CI")
class AuthenticatedExecutorPostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.role = "executor_harness_" + uuid.uuid4().hex
        cls.password = secrets.token_urlsafe(36)
        cls.connect_args = {
            "host": os.getenv("PGHOST", "localhost"),
            "port": int(os.getenv("PGPORT", "5432")),
            "dbname": os.getenv("PGDATABASE", "safety_test"),
            "user": os.getenv("PGUSER", "postgres"),
            "password": os.environ["PGPASSWORD"],
            "autocommit": True,
        }
        cls.admin = psycopg.connect(**cls.connect_args)
        cls.admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(cls.role), sql.Literal(cls.password)
            )
        )
        cls.admin.execute(
            sql.SQL("GRANT bot_entry_executor_trial TO {}").format(
                sql.Identifier(cls.role)
            )
        )

    @classmethod
    def tearDownClass(cls):
        cls.admin.execute(
            sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(cls.role))
        )
        cls.admin.close()

    def setUp(self):
        self.admin.execute(
            "TRUNCATE public.bot_entry_intents, public.bot_entry_reservations"
        )

    def connect_executor(self):
        return psycopg.connect(
            host=os.getenv("PGHOST", "localhost"),
            port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "safety_test"),
            user=self.role,
            password=self.password,
        )

    def executor_rpc(self):
        return restricted_executor_rpc(
            self.connect_executor,
            expected_login=self.role,
        )

    def run_trade(self, bot, action, coin, rpc=None):
        executor_index = ("aggressive", "intraday", "daily").index(bot)
        return execute_offline_authenticated_trade(
            execute_trade=load_function(FILES[executor_index]),
            trade={"hl_coin": coin, "action": action},
            bot=bot,
            jwt_token=signed_token(bot=bot),
            signing_keys=KEYS,
            issuer=ISSUER,
            audience=AUDIENCE,
            rpc=rpc or self.executor_rpc(),
            now=100,
        )

    def test_three_bots_compete_for_one_coin_and_only_one_claims(self):
        barrier = threading.Barrier(4)

        def attempt(bot):
            barrier.wait(timeout=10)
            return bot, self.run_trade(bot, "open_long", "BTC")

        bots = ("aggressive", "intraday", "daily")
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [pool.submit(attempt, bot) for bot in bots]
            barrier.wait(timeout=10)
            results = dict(job.result(timeout=20) for job in jobs)

        winners = [bot for bot, result in results.items() if result.claim is not None]
        self.assertEqual(len(winners), 1)
        self.assertTrue(all(result.trade_result["status"] == "blocked"
                            for result in results.values()))
        self.assertTrue(all(not result.live_order_submitted
                            and result.exchange_calls == ()
                            for result in results.values()))
        with self.admin.cursor() as cursor:
            rows = cursor.execute(
                "SELECT bot, status FROM public.bot_entry_intents WHERE coin='BTC'"
            ).fetchall()
        self.assertEqual(rows, [(winners[0], "pending")])

    def test_restart_and_uncertain_submission_keep_intent_fenced(self):
        first = self.run_trade("intraday", "open_short", "ETH")
        self.assertIsNotNone(first.claim)
        self.assertEqual(first.trade_result["status"], "blocked")
        self.admin.execute(
            "UPDATE public.bot_entry_intents SET status='uncertain' WHERE coin='ETH'"
        )

        # Seed the durable uncertain state as an external-order recovery fixture;
        # this offline harness never submits the order or calls market_open.
        restarted = self.run_trade("aggressive", "open_long", "ETH")
        self.assertIsNone(restarted.claim)
        self.assertEqual(restarted.failure, "PermissionError")
        self.assertFalse(restarted.live_order_submitted)
        self.assertEqual(restarted.exchange_calls, ())
        with self.admin.cursor() as cursor:
            status = cursor.execute(
                "SELECT status FROM public.bot_entry_intents WHERE coin='ETH'"
            ).fetchone()[0]
        self.assertEqual(status, "uncertain")

    def test_ambiguous_claim_response_remains_fenced_after_restart(self):
        rpc = self.executor_rpc()

        def claim_then_timeout(function, params):
            result = rpc(function, params)
            if function == "claim_bot_entry_intent":
                raise TimeoutError("simulated lost response after committed claim")
            return result

        first = self.run_trade("daily", "open_long", "SOL", rpc=claim_then_timeout)
        self.assertEqual(first.failure, "TimeoutError")
        self.assertIsNone(first.claim)
        self.assertFalse(first.live_order_submitted)
        self.assertEqual(first.exchange_calls, ())

        restarted = self.run_trade("intraday", "open_short", "SOL")
        self.assertIsNone(restarted.claim)
        self.assertEqual(restarted.failure, "PermissionError")
        with self.admin.cursor() as cursor:
            state = cursor.execute(
                "SELECT bot, status FROM public.bot_entry_intents WHERE coin='SOL'"
            ).fetchone()
        self.assertEqual(state, ("daily", "pending"))

    def test_database_outage_is_fail_closed(self):
        def unavailable_connection():
            raise ConnectionError("simulated disposable database outage")

        rpc = restricted_executor_rpc(
            unavailable_connection,
            expected_login=self.role,
        )
        result = self.run_trade("aggressive", "open_long", "AVAX", rpc=rpc)
        self.assertEqual(result.failure, "ConnectionError")
        self.assertIsNone(result.claim)
        self.assertFalse(result.live_order_submitted)
        self.assertEqual(result.exchange_calls, ())


if __name__ == "__main__":
    unittest.main()