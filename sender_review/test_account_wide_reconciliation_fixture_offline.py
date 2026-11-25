"""Account-wide synthetic reconciliation: never grants authority."""
from dataclasses import replace
import ast
import json
from pathlib import Path
import unittest

from sender_review.account_wide_reconciliation_fixture_offline import (
    SyntheticPosition, SyntheticOrder, SyntheticFill, SyntheticClaim,
    SyntheticAccountHistory, reconcile_close_fixture_offline,
)
ACCOUNT="0x"+"1"*40
REF="a"*32
OID="b"*32
CLOID="0x"+"c"*32
NONCE="d"*32


def payload(**changes):
    p=dict(version=1, action="protective_close", side="long", coin="SOL",
           request_nonce="e"*32, position_ref=REF, close_size="0.12",
           observed_position_size="0.20", exit_reason="trailing_protection",
           reduce_only=True)
    p.update(changes)
    return json.dumps(p).encode()


def history(**changes):
    order=SyntheticOrder(
        account=ACCOUNT, oid=OID, cloid=CLOID, nonce=NONCE,
        bot="daily", coin="SOL", position_ref=REF, side="buy",
        requested_size="0.20", status="filled", fence=4,
    )
    h=SyntheticAccountHistory(
        account=ACCOUNT, sampled_epoch=100,
        positions_complete=True, orders_complete=True,
        fills_complete=True, from_flat_baseline=True,
        positions=(SyntheticPosition(ACCOUNT,"SOL","0.20",REF),),
        orders=(order,),
        fills=(SyntheticFill("f"*32,OID,"0.20"),),
        claims=(SyntheticClaim("daily","SOL",REF,(OID,),4),),
    )
    return replace(h,**changes)


def review(h=None, **changes):
    params=dict(body=payload(),fixture_bot="daily",
                history=history() if h is None else h,
                expected_account=ACCOUNT,expected_fence=4,now_epoch=102)
    params.update(changes)
    return reconcile_close_fixture_offline(**params)


class AccountWideReconciliationTests(unittest.TestCase):
    def assert_hold(self, result):
        self.assertEqual(result.state,"HOLD")
        for name in (
            "runtime_identity_authenticated","account_scope_verified",
            "exchange_provenance_verified","ownership_verified",
            "nonce_consumed","fence_released","reduce_only_verified",
            "submit_authorized","close_authorized","retry_authorized",
            "signing_enabled",
        ):
            self.assertFalse(getattr(result,name),name)

    def test_consistent_fixture_is_not_real_provenance(self):
        for bot in ("daily","intraday","aggressive"):
            h=history(
                orders=(replace(history().orders[0],bot=bot),),
                claims=(SyntheticClaim(bot,"SOL",REF,(OID,),4),),
            )
            result=review(h,fixture_bot=bot)
            self.assertTrue(result.fixture_consistent)
            self.assertEqual(result.fixture_net_size,"0.20")
            self.assertEqual(result.fixture_attributed_bot,bot)
            self.assert_hold(result)

    def test_incomplete_stale_or_nonflat_baseline_holds(self):
        for item in (
            history(positions_complete=False),
            history(orders_complete=False),
            history(fills_complete=False),
            history(from_flat_baseline=False),
            history(sampled_epoch=80),
            history(sampled_epoch=110),
            history(account="0x"+"2"*40),
        ):
            with self.subTest(history=item):
                result=review(item)
                self.assertEqual(result.reason,"incomplete-or-stale-account-wide-history")
                self.assert_hold(result)

    def test_manual_unattributed_and_unresolved_orders_hold(self):
        base=history()
        for item in (
            history(orders=(replace(base.orders[0],bot="manual"),)),
            history(orders=(replace(base.orders[0],status="unknown_ack"),)),
            history(orders=(replace(base.orders[0],status="partial"),)),
            history(orders=(replace(base.orders[0],status="open"),)),
            history(orders=(replace(base.orders[0],status="not_sent"),)),
            history(orders=(replace(base.orders[0],side="sell"),)),
            history(orders=(replace(base.orders[0],cloid="malformed"),)),
        ):
            with self.subTest(history=item):
                result=review(item)
                self.assertFalse(result.fixture_consistent)
                self.assert_hold(result)

    def test_duplicate_fill_order_nonce_and_cloid_hold(self):
        base=history()
        duplicate_order=replace(base.orders[0],oid="1"*32)
        for item in (
            history(fills=(base.fills[0],base.fills[0])),
            history(fills=(SyntheticFill("f"*32,"0"*32,"0.20"),)),
            history(orders=(base.orders[0],duplicate_order)),
            history(orders=(base.orders[0],replace(duplicate_order,nonce="1"*32))),
            history(orders=(base.orders[0],replace(duplicate_order,cloid="0x"+"1"*32))),
        ):
            with self.subTest(history=item):
                result=review(item)
                self.assertFalse(result.fixture_consistent)
                self.assert_hold(result)

    def test_ambiguous_bot_claims_wrong_refs_and_fences_hold(self):
        base=history()
        for item in (
            history(claims=()),
            history(claims=(base.claims[0],base.claims[0])),
            history(claims=(replace(base.claims[0],bot="intraday"),)),
            history(claims=(replace(base.claims[0],fence=5),)),
            history(claims=(replace(base.claims[0],order_ids=("1"*32,)),)),
            history(orders=(replace(base.orders[0],bot="aggressive"),)),
            history(orders=(replace(base.orders[0],fence=5),)),
            history(orders=(replace(base.orders[0],position_ref="1"*32),)),
        ):
            with self.subTest(history=item):
                result=review(item)
                self.assertFalse(result.fixture_consistent)
                self.assert_hold(result)

    def test_partial_cancel_overfills_and_missing_position_mismatch_hold(self):
        base=history()
        for item in (
            history(positions=(replace(base.positions[0],signed_size="0.19"),)),
            history(positions=(replace(base.positions[0],signed_size="-0.20"),)),
            history(positions=(replace(base.positions[0],signed_size="NaN"),)),
            history(fills=(replace(base.fills[0],size="0.30"),)),
            history(fills=(replace(base.fills[0],size="0.10"),)),
            history(orders=(replace(base.orders[0],status="canceled"),)),
            history(positions=()),
        ):
            with self.subTest(history=item):
                result=review(item)
                self.assertFalse(result.fixture_consistent)
                self.assert_hold(result)

    def test_wrong_request_size_side_position_or_scope_holds(self):
        for body in (
            payload(close_size="0.21"),
            payload(side="short"),
            payload(position_ref="1"*32),
            payload(observed_position_size="0.19"),
            payload(action="close"),
            payload(reduce_only=False),
        ):
            with self.subTest(body=body):
                result=review(body=body)
                self.assertFalse(result.fixture_consistent)
                self.assert_hold(result)
        self.assert_hold(review(expected_fence=5))
        self.assert_hold(review(expected_account="0x"+"2"*40))

    def test_imports_are_pure_parser_only(self):
        p=Path(__file__).with_name("account_wide_reconciliation_fixture_offline.py")
        names=set()
        for n in ast.walk(ast.parse(p.read_text("utf-8"))):
            if isinstance(n,ast.Import):
                names.update(a.name for a in n.names)
            elif isinstance(n,ast.ImportFrom):
                names.add(n.module)
        self.assertEqual(names,{
            "dataclasses","decimal","json","re",
            "sender_review.proposed_intent_interfaces_offline",
        })


if __name__=="__main__":
    unittest.main()
