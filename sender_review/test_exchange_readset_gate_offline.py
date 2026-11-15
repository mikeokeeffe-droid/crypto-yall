"""Offline synthetic read-set gate: no real exchange origin or close authority."""
from dataclasses import replace
import ast
from pathlib import Path
import unittest

from sender_review.exchange_readset_gate_offline import (
    SyntheticExchangePage, SyntheticReadSet,
    inspect_exchange_readset_fixture_offline,
    inspect_close_reconciliation_with_readset_offline,
)
from sender_review.test_account_wide_reconciliation_fixture_offline import (
    ACCOUNT, history, payload,
)

BATCH="a"*32
DIGEST="f"*64


def page(endpoint, **changes):
    defaults=dict(
        endpoint=endpoint,account=ACCOUNT,network="testnet",
        batch_id=BATCH,page_number=0,input_cursor=None,
        next_cursor=None,record_ids=(),sampled_epoch=100,
        claimed_success=True,claimed_not_truncated=True,
        claimed_position_digest=(
            DIGEST if endpoint.startswith("positions_") else None
        ),
    )
    defaults.update(changes)
    return SyntheticExchangePage(**defaults)


def manifest(**changes):
    initial=SyntheticReadSet(pages=(
        page("positions_before",record_ids=("1"*32,)),
        page("orders",record_ids=("2"*32,)),
        page("fills",record_ids=("3"*32,)),
        page("open_orders"),
        page("positions_after",record_ids=("1"*32,)),
    ))
    return replace(initial,**changes)


def gate(m=None, **changes):
    args=dict(readset=manifest() if m is None else m,
              expected_account=ACCOUNT,now_epoch=102)
    args.update(changes)
    return inspect_exchange_readset_fixture_offline(**args)


class OfflineExchangeReadsetGateTests(unittest.TestCase):
    def assert_no_authority(self, result):
        self.assertEqual(result.state,"HOLD")
        for attr in (
            "runtime_identity_authenticated","exchange_transport_authenticated",
            "account_history_verified","position_ownership_verified",
            "read_only_adapter_deployed","request_authorized",
            "close_authorized","retry_authorized","fence_released",
            "signing_enabled",
        ):
            self.assertFalse(getattr(result,attr),attr)

    def test_coherent_manifest_is_still_untrusted(self):
        result=gate()
        self.assertTrue(result.fixture_manifest_coherent)
        self.assert_no_authority(result)
        composed=inspect_close_reconciliation_with_readset_offline(
            body=payload(),fixture_bot="daily",history=history(),
            expected_account=ACCOUNT,expected_fence=4,
            now_epoch=102,readset=manifest(),
        )
        self.assertTrue(composed.fixture_manifest_coherent)
        self.assertTrue(composed.fixture_reconciliation_coherent)
        self.assert_no_authority(composed)

    def test_complete_two_page_orders_uses_exact_cursor_chain(self):
        pages=list(manifest().pages)
        pages[1:2]=[
            page("orders",next_cursor="a"*32,
                 record_ids=("2"*32,)),
            page("orders",page_number=1,input_cursor="a"*32,
                 record_ids=("4"*32,)),
        ]
        self.assertTrue(gate(manifest(pages=tuple(pages))).fixture_manifest_coherent)
        self.assert_no_authority(gate(manifest(pages=tuple(pages))))

    def test_missing_pages_failed_pages_and_incomplete_cursor_hold(self):
        original=list(manifest().pages)
        cases=[
            tuple(original[:3]+original[4:]),
            tuple(original[:2]+original[3:]),
            tuple(original[:4]),
            tuple(original[:1]+[replace(original[1],claimed_success=False)]+original[2:]),
            tuple(original[:1]+[replace(original[1],claimed_not_truncated=False)]+original[2:]),
            tuple(original[:1]+[replace(original[1],next_cursor="a"*32)]+original[2:]),
            tuple(original[:1]+[replace(original[1],page_number=2)]+original[2:]),
            tuple(original[:1]+[replace(original[1],record_ids=("2"*32,"2"*32))]+original[2:]),
        ]
        for pages in cases:
            with self.subTest(pages=pages):
                result=gate(manifest(pages=pages))
                self.assertFalse(result.fixture_manifest_coherent)
                self.assert_no_authority(result)

    def test_wrong_network_account_batch_future_stale_and_changed_bookends_hold(self):
        original=list(manifest().pages)
        cases=(
            (1,{"network":"mainnet"}),
            (1,{"account":"0x"+"2"*40}),
            (1,{"batch_id":"b"*32}),
            (1,{"sampled_epoch":110}),
            (1,{"sampled_epoch":80}),
            (4,{"claimed_position_digest":"e"*64}),
            (4,{"claimed_position_digest":None}),
            (2,{"claimed_position_digest":DIGEST}),
            (3,{"record_ids":("0"*32,)*501}),
        )
        for i,changes in cases:
            with self.subTest(index=i,changes=changes):
                pages=list(original)
                pages[i]=replace(pages[i],**changes)
                result=gate(manifest(pages=tuple(pages)))
                self.assertFalse(result.fixture_manifest_coherent)
                self.assert_no_authority(result)

    def test_cursor_gap_and_duplicate_endpoint_records_hold(self):
        original=list(manifest().pages)
        malformed_orders=[
            (
                page("orders",next_cursor="a"*32,record_ids=("2"*32,)),
                page("orders",page_number=1,input_cursor="b"*32,
                     record_ids=("4"*32,)),
            ),
            (
                page("orders",next_cursor="a"*32,record_ids=("2"*32,)),
                page("orders",page_number=1,input_cursor="a"*32,
                     next_cursor="b"*32,record_ids=("4"*32,)),
            ),
            (
                page("orders",next_cursor="a"*32,record_ids=("2"*32,)),
                page("orders",page_number=1,input_cursor="a"*32,
                     record_ids=("2"*32,)),
            ),
        ]
        for group in malformed_orders:
            pages=tuple(original[:1]+list(group)+original[2:])
            result=gate(manifest(pages=pages))
            self.assertFalse(result.fixture_manifest_coherent)
            self.assert_no_authority(result)

    def test_unresolved_ack_and_bad_claims_hold(self):
        result=gate(manifest(outstanding_unknown_order_ids=("e"*32,)))
        self.assertEqual(result.reason,"unknown-ack-still-unresolved")
        self.assert_no_authority(result)
        for unknown in ((None,),("bad",),["e"*32]):
            with self.subTest(unknown=unknown):
                result=gate(manifest(outstanding_unknown_order_ids=unknown))
                self.assertFalse(result.fixture_manifest_coherent)
                self.assert_no_authority(result)

    def test_consistent_manifest_cannot_override_inconsistent_history(self):
        bad=history(fills=())
        result=inspect_close_reconciliation_with_readset_offline(
            body=payload(),fixture_bot="daily",history=bad,
            expected_account=ACCOUNT,expected_fence=4,
            now_epoch=102,readset=manifest(),
        )
        self.assertTrue(result.fixture_manifest_coherent)
        self.assertFalse(result.fixture_reconciliation_coherent)
        self.assert_no_authority(result)

    def test_module_imports_only_pure_stdlib_and_offline_reconciler(self):
        source=Path(__file__).with_name(
            "exchange_readset_gate_offline.py").read_text("utf-8")
        names=set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node,ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node,ast.ImportFrom):
                names.add(node.module)
        self.assertEqual(names,{
            "dataclasses","re",
            "sender_review.account_wide_reconciliation_fixture_offline",
        })


if __name__=="__main__":
    unittest.main()
