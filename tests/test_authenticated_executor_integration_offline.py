"""Offline composition tests; executor functions run only with a fake exchange."""
import unittest

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
from trusted_executor_jwt_staging import ExecutorAuthenticationError


class RecordingRpc:
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def __call__(self, function, params):
        self.calls.append(function)
        if self.fail_at == function:
            raise ConnectionError("simulated disposable-store outage")
        return True


class AuthenticatedExecutorHarnessOfflineTests(unittest.TestCase):
    def run_trade(self, bot, action, rpc, token=None):
        index = ("aggressive", "intraday", "daily").index(bot)
        return execute_offline_authenticated_trade(
            execute_trade=load_function(FILES[index]),
            trade={"hl_coin": "BTC", "action": action},
            bot=bot,
            jwt_token=token or signed_token(bot=bot),
            signing_keys=KEYS,
            issuer=ISSUER,
            audience=AUDIENCE,
            rpc=rpc,
            now=100,
        )

    def test_authenticated_entry_claims_never_reach_fake_order_methods(self):
        for bot in ("aggressive", "intraday", "daily"):
            for action in ("open_long", "open_short", "pyramid_long", "pyramid_short"):
                with self.subTest(bot=bot, action=action):
                    rpc = RecordingRpc()
                    result = self.run_trade(bot, action, rpc)
                    self.assertEqual(result.trade_result["status"], "blocked")
                    self.assertTrue(result.claim.claimed)
                    self.assertFalse(result.claim.live_order_authorized)
                    self.assertFalse(result.live_order_submitted)
                    self.assertEqual(result.exchange_calls, ())
                    self.assertEqual(
                        rpc.calls,
                        ["try_reserve_bot_entry", "claim_bot_entry_intent"],
                    )

    def test_rejected_authentication_never_calls_database_or_exchange(self):
        rpc = RecordingRpc()
        result = self.run_trade(
            "aggressive", "open_long", rpc, token=signed_token(bot="daily")
        )
        self.assertEqual(result.failure, ExecutorAuthenticationError.__name__)
        self.assertIsNone(result.claim)
        self.assertFalse(result.live_order_submitted)
        self.assertEqual(rpc.calls, [])
        self.assertEqual(result.exchange_calls, ())

    def test_expired_token_never_calls_database_or_exchange(self):
        rpc = RecordingRpc()
        result = self.run_trade(
            "intraday",
            "open_long",
            rpc,
            token=signed_token(bot="intraday", expires=100),
        )
        self.assertEqual(result.failure, ExecutorAuthenticationError.__name__)
        self.assertIsNone(result.claim)
        self.assertEqual(rpc.calls, [])
        self.assertEqual(result.exchange_calls, ())

    def test_database_outage_fails_closed_without_order_attempt(self):
        rpc = RecordingRpc(fail_at="try_reserve_bot_entry")
        result = self.run_trade("intraday", "open_short", rpc)
        self.assertEqual(result.failure, "ConnectionError")
        self.assertEqual(rpc.calls, ["try_reserve_bot_entry"])
        self.assertIsNone(result.claim)
        self.assertFalse(result.live_order_submitted)
        self.assertEqual(result.exchange_calls, ())

    def test_database_claim_outage_fails_closed_without_order_attempt(self):
        rpc = RecordingRpc(fail_at="claim_bot_entry_intent")
        result = self.run_trade("daily", "open_long", rpc)
        self.assertEqual(result.failure, "ConnectionError")
        self.assertEqual(
            rpc.calls,
            ["try_reserve_bot_entry", "claim_bot_entry_intent"],
        )
        self.assertIsNone(result.claim)
        self.assertFalse(result.live_order_submitted)
        self.assertEqual(result.exchange_calls, ())

    def test_closes_bypass_authentication_and_reservation_gateway(self):
        for bot in ("aggressive", "intraday", "daily"):
            with self.subTest(bot=bot):
                rpc = RecordingRpc(fail_at="try_reserve_bot_entry")
                result = self.run_trade(bot, "close", rpc, token="invalid")
                self.assertEqual(result.trade_result["status"], "filled")
                self.assertIsNone(result.claim)
                self.assertEqual(rpc.calls, [])
                self.assertEqual(
                    [call[0] for call in result.exchange_calls], ["market_close"]
                )
                self.assertFalse(result.live_order_submitted)

    def test_partial_closes_preserve_requested_size_for_all_bots(self):
        for bot in ("aggressive", "intraday", "daily"):
            with self.subTest(bot=bot):
                result = execute_offline_authenticated_trade(
                    execute_trade=load_function(FILES[("aggressive", "intraday", "daily").index(bot)]),
                    trade={"hl_coin": "BTC", "action": "close", "close_size": 0.25},
                    bot=bot,
                    jwt_token="invalid-token-is-ignored-for-close",
                    signing_keys=KEYS,
                    issuer=ISSUER,
                    audience=AUDIENCE,
                    rpc=RecordingRpc(),
                    now=100,
                )
                self.assertEqual(result.trade_result["status"], "filled")
                self.assertIsNone(result.claim)
                self.assertEqual(result.exchange_calls[0][0], "market_close")
                self.assertEqual(result.exchange_calls[0][1:], ("BTC", 0.25))


if __name__ == "__main__":
    unittest.main()