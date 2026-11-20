"""Six synthetic /info frames -> signer-free worker -> only aggregate HOLD."""
import ast
from dataclasses import replace
import json
from pathlib import Path
import unittest

from sender_review.six_frame_shadow_pipeline_offline import (
    inspect_six_frame_shadow_pipeline_offline,
)
from sender_review.test_six_frame_payload_binding_offline import (
    sample, ACCOUNT, START, END,
)


def fixture_frames(account_value="100", szi="0.20"):
    frames = sample()
    original = json.loads(frames[0].response_body)
    original["marginSummary"] = {"accountValue": account_value}
    original["assetPositions"][0]["position"].update({
        "szi": szi, "entryPx": "100",
        "unrealizedPnl": "1", "leverage": {"type": "cross", "value": 2},
    })
    payload = json.dumps(original, separators=(",", ":")).encode("ascii")
    return (
        replace(frames[0], response_body=payload),
        *frames[1:5],
        replace(frames[5], response_body=payload),
    )


def run(frames=None, bot="daily", **changes):
    args = dict(
        account=ACCOUNT, start_time_ms=START, end_time_ms=END,
        frames=fixture_frames() if frames is None else frames,
        bot=bot, signals={"SOL-USD": {"action": "sell_exit"}},
        max_positions=2, synthetic_now_epoch=1700000000,
    )
    args.update(changes)
    return inspect_six_frame_shadow_pipeline_offline(**args)


class SixFrameShadowPipelineTests(unittest.TestCase):
    def deny_authority(self, result):
        for field in (
            "network_performed", "exchange_origin_authenticated",
            "account_scope_verified", "historical_completeness_verified",
            "position_ownership_verified", "runtime_identity_authenticated",
            "effective_reduce_only_verified", "durable_fence_reserved",
            "submit_authorized", "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, field), False, field)

    def test_three_bots_get_only_inert_close_counts(self):
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                result = run(bot=bot)
                self.assertEqual(
                    result.state, "SYNTHETIC_SIX_FRAME_SHADOW_REPORT_HOLD",
                    result.reason,
                )
                self.assertTrue(result.shadow_reviewable)
                self.assertEqual(result.frame_count, 6)
                self.assertEqual(result.close_candidate_count, 1)
                self.assertEqual(result.deferred_entry_count, 0)
                self.assertNotIn("SOL", repr(result))
                self.assertNotIn("close_size", repr(result))
                self.deny_authority(result)

    def test_full_snapshot_mismatch_is_not_readiness(self):
        frames = fixture_frames()
        after = json.loads(frames[5].response_body)
        for field, value in (("unrealizedPnl", "2"), ("entryPx", "101")):
            with self.subTest(field=field):
                changed = json.loads(frames[5].response_body)
                changed["assetPositions"][0]["position"][field] = value
                bad = frames[:5] + (replace(
                    frames[5],
                    response_body=json.dumps(changed).encode("ascii"),
                ),)
                result = run(frames=bad)
                self.assertEqual(result.state, "HOLD")
                self.assertFalse(result.shadow_reviewable)
                self.deny_authority(result)
        changed = json.loads(frames[5].response_body)
        changed["marginSummary"]["accountValue"] = "101"
        bad = frames[:5] + (replace(
            frames[5], response_body=json.dumps(changed).encode("ascii"),
        ),)
        self.assertFalse(run(frames=bad).shadow_reviewable)

    def test_low_equity_requires_missing_spot_seventh_read(self):
        result = run(frames=fixture_frames(account_value="5"))
        self.assertEqual(result.state, "HOLD")
        self.assertTrue(result.missing_spot_read)
        self.assertFalse(result.shadow_reviewable)
        self.deny_authority(result)

    def test_wrong_request_missing_frame_and_open_order_fail_closed(self):
        frames = fixture_frames()
        for bad in (
            frames[:5],
            frames[1:],
            frames[:1] + (replace(frames[1], host="api.hyperliquid.xyz"),) + frames[2:],
            frames[:1] + (replace(frames[1], response_body=b'[{"oid":1}]'),) + frames[2:],
            frames[:3] + (replace(frames[3], response_body=b"[]"),) + frames[4:],
            list(frames),
        ):
            with self.subTest(bad=str(bad)[:50]):
                result = run(frames=bad)
                self.assertFalse(result.shadow_reviewable)
                self.assertEqual(result.state, "HOLD")
                self.deny_authority(result)

    def test_no_fabricated_account_or_invalid_signal_is_passed_as_ready(self):
        for changes in (
            {"signals": {"SOL-USD": {"action": "unknown"}}},
            {"bot": "untrusted"},
            {"max_positions": True},
            {"protection_enabled": False, "bot": "intraday"},
        ):
            with self.subTest(change=changes):
                result = run(**changes)
                self.assertFalse(result.shadow_reviewable)
                self.deny_authority(result)

    def test_module_imports_only_pure_offline_components(self):
        path = Path(__file__).with_name("six_frame_shadow_pipeline_offline.py")
        imports = set()
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {
            "dataclasses", "json",
            "sender_review.six_frame_payload_binding_offline",
            "sender_review.composed_shadow_worker_offline",
            "sender_review.shadow_report_boundary_offline",
        })


if __name__ == "__main__":
    unittest.main()
