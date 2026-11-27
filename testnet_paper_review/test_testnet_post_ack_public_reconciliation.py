"""No-network post-ACK public /info snapshot and protection tests."""
from copy import deepcopy
from dataclasses import replace
import ast
from pathlib import Path
import unittest

from testnet_paper_review.testnet_post_ack_public_reconciliation import (
    review_public_post_ack_once, PostAckPublicHold
)
from testnet_paper_review.test_offline_bracket_reconciliation import proof


class FakeReads:
    def __init__(self, fixture, *, mutate=None, fail_at=None):
        self.fixture=fixture
        self.mutate=mutate
        self.fail_at=fail_at
        self.calls=[]
    def __call__(self, kind):
        self.calls.append(kind)
        count=len(self.calls)
        if count==self.fail_at:
            raise TimeoutError("synthetic public info timeout")
        if kind=="clearinghouseState":
            value={"assetPositions":deepcopy(self.fixture["positions"])}
        elif kind=="openOrders":
            value=deepcopy(self.fixture["open_orders"])
        elif kind=="frontendOpenOrders":
            value=deepcopy(self.fixture["frontend_open_orders"])
        else:
            raise AssertionError("unexpected public read")
        if self.mutate is not None and count>3:
            value=self.mutate(kind,value)
        return value


def run(*, changes=None, mutate=None, clock=None, reader=None):
    case=proof()
    if changes:case.update(changes)
    reads=reader or FakeReads(case,mutate=mutate)
    result=review_public_post_ack_once(
        plan=case["plan"],response=case["response"],
        reader=reads,clock=clock or (lambda:case["now_s"])
    )
    return result,reads


class TestPostAckPublicReconciliation(unittest.TestCase):
    def test_complete_position_and_both_exits_still_review_only(self):
        result,reader=run()
        self.assertFalse(result.may_send)
        self.assertFalse(result.guarantees_stop_execution)
        self.assertEqual(result.position_count,1)
        self.assertEqual(result.open_protection_count,2)
        self.assertEqual([result.entry_oid,result.take_profit_oid,result.stop_loss_oid],
                         [101,102,103])
        self.assertEqual(reader.calls,[
            "clearinghouseState","openOrders","frontendOpenOrders"]*2)

    def test_missing_or_changed_stop_between_snapshots_fails_closed(self):
        def drop_stop(kind,value):
            return value[:-1] if kind in ("openOrders","frontendOpenOrders") else value
        with self.assertRaises(PostAckPublicHold):
            run(mutate=drop_stop)

    def test_missing_stop_in_both_snapshots_fails_closed(self):
        for key in ("open_orders","frontend_open_orders"):
            case=proof()
            case[key].pop()
            with self.subTest(key=key),self.assertRaises(PostAckPublicHold):
                review_public_post_ack_once(plan=case["plan"],response=case["response"],
                    reader=FakeReads(case),clock=lambda:case["now_s"])

    def test_account_changes_or_foreign_positions_hold(self):
        def unexpected_position(kind,value):
            if kind=="clearinghouseState":
                value["assetPositions"].append({"position":{"coin":"ETH","szi":"1"}})
            return value
        with self.assertRaises(PostAckPublicHold):
            run(mutate=unexpected_position)
        case=proof()
        case["positions"].append({"position":{"coin":"ETH","szi":"1"}})
        with self.assertRaises(PostAckPublicHold):
            review_public_post_ack_once(plan=case["plan"],response=case["response"],
                reader=FakeReads(case),clock=lambda:case["now_s"])

    def test_timeout_in_each_public_read_is_hold(self):
        case=proof()
        for count in range(1,7):
            with self.subTest(count=count),self.assertRaises(PostAckPublicHold):
                review_public_post_ack_once(plan=case["plan"],response=case["response"],
                    reader=FakeReads(case,fail_at=count),clock=lambda:case["now_s"])

    def test_bad_fill_ack_and_network_and_clock_hold(self):
        case=proof()
        for response in ({},{"status":"error"},None):
            with self.subTest(response=response),self.assertRaises(PostAckPublicHold):
                review_public_post_ack_once(plan=case["plan"],response=response,
                    reader=FakeReads(case),clock=lambda:case["now_s"])
        with self.assertRaises(PostAckPublicHold):
            review_public_post_ack_once(plan=case["plan"],response=case["response"],
                network="hyperliquid-mainnet",reader=FakeReads(case),clock=lambda:case["now_s"])
        ticks=iter((case["now_s"]-11,case["now_s"]))
        with self.assertRaises(PostAckPublicHold):
            review_public_post_ack_once(plan=case["plan"],response=case["response"],
                reader=FakeReads(case),clock=lambda:next(ticks))

    def test_does_not_import_signers_or_exchange_or_sender(self):
        import testnet_paper_review.testnet_post_ack_public_reconciliation as mod
        tree=ast.parse(Path(mod.__file__).read_text())
        imports={n.module for n in ast.walk(tree)
                 if isinstance(n,ast.ImportFrom) and n.module}
        self.assertFalse(any(x.startswith((
            "hyperliquid.exchange","eth_account","testnet_paper_review.isolated_testnet_sender"
        )) for x in imports))
        methods={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertFalse({"send_once","submit_order","market_open","market_close","sign"} & methods)


if __name__=="__main__":
    unittest.main()
