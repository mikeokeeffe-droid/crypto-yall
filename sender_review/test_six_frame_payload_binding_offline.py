"""Six public-info synthetic responses joined to exact request bytes, no I/O."""
from dataclasses import replace
import json
import unittest

from sender_review.six_frame_payload_binding_offline import (
    SyntheticInfoFrame, inspect_synthetic_info_payload_binding_offline,
)
from sender_review.hyperliquid_readonly_collection_plan_offline import (
    plan_offline_six_frame_reconciliation_fixture,
)

ACCOUNT = "0x" + "1"*40
START = 1000
END = 2000


def sample():
    position = {"assetPositions": [
        {"position": {"coin": "SOL", "szi": "0.20"}},
    ]}
    order = {"status": "filled", "order": {
        "oid": 123, "coin": "SOL", "side": "B",
        "origSz": "0.20", "timestamp": 1200,
    }}
    fill = {"oid": 123, "tid": 456, "coin": "SOL",
            "side": "B", "sz": "0.20", "time": 1300}
    bodies = (position, [], [order], [fill], [], position)
    plan = plan_offline_six_frame_reconciliation_fixture(
        account=ACCOUNT, start_time_ms=START, end_time_ms=END)
    assert len(plan.queries) == 6
    return tuple(SyntheticInfoFrame(
        step=index, scheme=query.scheme, host=query.host,
        method=query.method, path=query.path,
        content_type=query.content_type,
        request_body=query.body_json.encode("ascii"),
        claimed_status_code=200,
        response_body=json.dumps(doc, separators=(",", ":")).encode("ascii"))
        for index, (query, doc) in enumerate(zip(plan.queries, bodies), 1))


def review(frames, **changes):
    args = dict(account=ACCOUNT, start_time_ms=START,
                end_time_ms=END, frames=frames)
    args.update(changes)
    return inspect_synthetic_info_payload_binding_offline(**args)


class SyntheticInfoPayloadBindingTests(unittest.TestCase):
    def assert_denied(self, result):
        self.assertEqual(result.state, "HOLD")
        for flag in (
            "network_performed", "authenticated_tls_origin",
            "authenticated_response_provenance",
            "account_identity_verified", "historical_coverage_verified",
            "position_ownership_verified", "durable_fence_reserved",
            "submit_authorized", "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, flag), False, flag)

    def test_six_matching_synthetic_frames_remain_non_authorizing(self):
        r = review(sample())
        self.assert_denied(r)
        self.assertTrue(r.exact_synthetic_wiring)
        self.assertTrue(r.locally_consistent)
        self.assertEqual(r.frames_reviewed, 6)
        self.assertEqual(len(r.observed_request_sha256), 6)
        self.assertEqual(len(r.observed_response_sha256), 6)

    def test_miswired_request_or_transport_claim_fails_closed(self):
        records = sample()
        cases = (
            {"step": 5}, {"method": "GET"}, {"path": "/exchange"},
            {"host": "api.hyperliquid.xyz"},
            {"scheme": "http"}, {"content_type": "text/plain"},
            {"request_body": records[3].request_body + b" "},
            {"request_body": records[2].request_body},
            {"claimed_status_code": 400}, {"claimed_status_code": True},
            {"response_body": b""}, {"response_body": b"[]" * 300000},
            {"response_body": b'{"duplicate":1,"duplicate":2}'},
            {"response_body": b"{broken"},
            {"response_body": b"NaN"},
        )
        for change in cases:
            with self.subTest(change=str(change)[:90]):
                frames = records[:3] + (replace(records[3], **change),) + records[4:]
                r = review(frames)
                self.assert_denied(r)
                self.assertFalse(r.exact_synthetic_wiring)

    def test_missing_extra_reordered_wrong_account_all_hold(self):
        records = sample()
        for frames in (records[:5], records + records[-1:],
                       (records[1], records[0]) + records[2:],
                       list(records), None):
            r = review(frames)
            self.assert_denied(r)
            self.assertFalse(r.exact_synthetic_wiring)
        self.assertFalse(review(records, account="0x"+"2"*40).exact_synthetic_wiring)

    def test_syntactically_valid_but_conflicting_responses_hold(self):
        records = sample()
        different = replace(records[5], response_body=b'{"assetPositions":[]}')
        r = review(records[:5] + (different,))
        self.assert_denied(r)
        self.assertTrue(r.exact_synthetic_wiring)
        self.assertFalse(r.locally_consistent)

    def test_local_history_coherence_does_not_imply_strategy_data_ready(self):
        # The original lightweight six-frame fixture has only position sizes
        # and no equity/entryPx/unrealizedPnl fields. It may reconcile locally
        # but must NOT be presented as a usable strategy account snapshot.
        result = review(sample())
        self.assertTrue(result.locally_consistent)
        self.assertFalse(result.strategy_shape_compatible)
        self.assertFalse(result.additional_spot_read_needed)
        self.assert_denied(result)

    def test_matching_full_strategy_shape_remains_non_authorizing(self):
        records = sample()
        position = json.loads(records[0].response_body)
        position["marginSummary"] = {"accountValue": "100"}
        position["assetPositions"][0]["position"].update({
            "entryPx": "120", "unrealizedPnl": "2",
            "leverage": {"value": 2},
        })
        raw = json.dumps(position, separators=(",", ":")).encode("ascii")
        frames = (
            replace(records[0], response_body=raw),
            *records[1:5],
            replace(records[5], response_body=raw),
        )
        result = review(frames)
        self.assertTrue(result.locally_consistent)
        self.assertTrue(result.strategy_shape_compatible)
        self.assertFalse(result.additional_spot_read_needed)
        self.assert_denied(result)

    def test_changed_equity_or_low_equity_spot_gap_blocks_compatibility(self):
        records = sample()
        full = json.loads(records[0].response_body)
        full["marginSummary"] = {"accountValue": "100"}
        full["assetPositions"][0]["position"].update({
            "entryPx": "120", "unrealizedPnl": "2",
            "leverage": {"value": 2},
        })
        def framed(start, end):
            before = json.dumps(start, separators=(",", ":")).encode("ascii")
            after = json.dumps(end, separators=(",", ":")).encode("ascii")
            return (
                replace(records[0], response_body=before),
                *records[1:5],
                replace(records[5], response_body=after),
            )
        changed = json.loads(json.dumps(full))
        changed["marginSummary"]["accountValue"] = "90"
        result = review(framed(full, changed))
        self.assertTrue(result.locally_consistent)
        self.assertFalse(result.strategy_shape_compatible)
        self.assert_denied(result)

        low = json.loads(json.dumps(full))
        low["marginSummary"]["accountValue"] = "5"
        result = review(framed(low, low))
        self.assertTrue(result.locally_consistent)
        self.assertTrue(result.additional_spot_read_needed)
        self.assertFalse(result.strategy_shape_compatible)
        self.assert_denied(result)

    def test_decimal_equity_and_raw_bookend_changes_hold(self):
        # A float compatibility projection rounds away this tiny difference;
        # original raw account observations must not appear stable.
        records = sample()
        base = json.loads(records[0].response_body)
        base["marginSummary"] = {"accountValue": "100"}
        base["assetPositions"][0]["position"].update({
            "entryPx": "120", "unrealizedPnl": "2",
            "leverage": {"value": 2},
        })
        changed_equity = json.loads(json.dumps(base))
        changed_equity["marginSummary"]["accountValue"] = "100.000000000000001"
        self.assertEqual(
            float(changed_equity["marginSummary"]["accountValue"]),
            float(base["marginSummary"]["accountValue"]),
        )
        changed_raw_position = json.loads(json.dumps(base))
        changed_raw_position["assetPositions"][0]["position"]["unrealizedPnl"] = "2.0000000000000001"
        self.assertEqual(float(changed_raw_position["assetPositions"][0]["position"]["unrealizedPnl"]), 2.0)
        for changed in (changed_equity, changed_raw_position):
            with self.subTest(changed=changed):
                before = json.dumps(base, separators=(",", ":")).encode("ascii")
                after = json.dumps(changed, separators=(",", ":")).encode("ascii")
                frames = (
                    replace(records[0], response_body=before),
                    *records[1:5],
                    replace(records[5], response_body=after),
                )
                result = review(frames)
                self.assertTrue(result.locally_consistent)
                self.assertFalse(result.strategy_shape_compatible)
                self.assert_denied(result)

    def test_no_network_or_exchange_dependencies(self):
        import ast
        from pathlib import Path
        source = Path(__file__).with_name(
            "six_frame_payload_binding_offline.py").read_text("utf-8")
        modules = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module)
        self.assertEqual(modules, {
            "dataclasses", "decimal", "hashlib", "json",
            "sender_review.hyperliquid_readonly_collection_plan_offline",
            "sender_review.coordinated_testnet_readset_review",
            "sender_review.signer_free_account_view_offline",
        })


if __name__ == "__main__":
    unittest.main()
