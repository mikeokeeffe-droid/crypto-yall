"""Mock-only integration tests for Daily SOL Testnet preflight."""
import unittest
from testnet_paper_review.testnet_daily_public_pipeline import review_testnet_daily_once, TestnetPipelineHold
from testnet_paper_review.test_daily_testnet_signal_adapter import BAR, OBS
from testnet_paper_review.test_testnet_daily_readonly_preflight import state


def signal(**changes):
    x={"ticker":"SOL-USD","last_signal":1,"prior_signal":0,"regime":"Bull",
       "action":"buy","bar_started_at_s":BAR,"observed_at_s":OBS,
       "legacy_leverage":3.0}
    x.update(changes)
    return x


def market(kind):
    return ({"universe":[{"name":"SOL","szDecimals":3,"maxLeverage":10}]}
            if kind=="meta" else {"SOL":"66.40"})


class Account:
    def __init__(self, positions=None, orders=None, detailed=None, mutate=False):
        self.calls=[]
        self.positions=positions
        self.orders=[] if orders is None else orders
        self.detailed=[] if detailed is None else detailed
        self.mutate=mutate
    def __call__(self, kind):
        self.calls.append(kind)
        if kind=="clearinghouseState":
            positions=self.positions
            if self.mutate and len(self.calls)>3:
                positions=[{"position":{"coin":"SOL","szi":"0.30"}}]
            return state(positions)
        return self.orders if kind=="openOrders" else self.detailed


def trial(account=None, facts=None, market_reader=market, clock=None, **kwargs):
    return review_testnet_daily_once(
        signal_fact=signal() if facts is None else facts,
        fetch_account=Account() if account is None else account,
        fetch_market=market_reader,clock=clock or (lambda:OBS+1),
        **kwargs
    )


class TestTestnetDailyPublicPipeline(unittest.TestCase):
    def test_clear_account_only_produces_nontrading_review_plan(self):
        acc=Account()
        result=trial(account=acc)
        self.assertEqual(result.status,"READY_FOR_HUMAN_REVIEW_ONLY")
        self.assertFalse(result.permits_submission)
        self.assertFalse(result.plan.permits_submission)
        self.assertEqual(result.size_decimals,3)
        self.assertEqual(result.observed_orders,0)
        self.assertLessEqual(float(result.planned_notional),20)
        self.assertEqual(acc.calls,["clearinghouseState","openOrders","frontendOpenOrders"]*2)

    def test_manual_positions_or_existing_protection_block(self):
        for coin in ("SOL","ETH","BTC"):
            with self.subTest(coin=coin),self.assertRaises(TestnetPipelineHold):
                trial(account=Account(positions=[{"position":{"coin":coin,"szi":"0.3"}}]))
        basic=[{"oid":1,"coin":"SOL","side":"A","sz":"0.3"}]
        rich=[{**basic[0],"reduceOnly":True,"isTrigger":True,
               "orderType":"Stop Market","triggerPx":"65.69"}]
        with self.assertRaises(TestnetPipelineHold):
            trial(account=Account(orders=basic,detailed=rich))
        with self.assertRaises(TestnetPipelineHold):
            trial(account=Account(mutate=True))

    def test_public_account_timeout_is_a_wrapped_hold(self):
        def fail_account(kind):
            raise TimeoutError("read-only account query timeout")
        with self.assertRaises(TestnetPipelineHold) as error:
            trial(account=fail_account)
        self.assertIn("HOLD",str(error.exception))

    def test_public_market_timeout_is_a_wrapped_hold(self):
        def fail_market(kind):
            raise OSError("read-only market query unreachable")
        with self.assertRaises(TestnetPipelineHold) as error:
            trial(market_reader=fail_market)
        self.assertIn("HOLD",str(error.exception))

    def test_invalid_market_and_daily_signals_block(self):
        for bad in ({}, {"SOL":"nan"}, {"SOL":"0"}):
            def bad_market(kind):
                return market("meta") if kind=="meta" else bad
            with self.subTest(bad=bad),self.assertRaises(TestnetPipelineHold):
                trial(market_reader=bad_market)
        for change in (
            {"action":"hold_long","prior_signal":1},{"ticker":"ETH-USD"},
            {"bar_started_at_s":BAR+60},{"observed_at_s":OBS-30},
        ):
            with self.subTest(change=change),self.assertRaises(TestnetPipelineHold):
                trial(facts=signal(**change))

    def test_wrong_budget_and_timing_block(self):
        with self.assertRaises(TestnetPipelineHold):
            trial(notional_usdc="100")
        ticks=iter((OBS+1,OBS+2,OBS+3,OBS+20))
        with self.assertRaises(TestnetPipelineHold):
            trial(clock=lambda:next(ticks))

    def test_no_signing_or_order_submission_capability(self):
        import ast
        from pathlib import Path
        import testnet_paper_review.testnet_daily_public_pipeline as mod
        tree=ast.parse(Path(mod.__file__).read_text())
        names={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertFalse({"sign","submit_order","execute_trade","market_open","market_close"} & names)
        imports={n.module.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n,ast.ImportFrom) and n.module}
        self.assertFalse({"hyperliquid","eth_account","requests","subprocess"} & imports)


if __name__=="__main__":
    unittest.main()
