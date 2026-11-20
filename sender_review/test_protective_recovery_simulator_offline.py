"""Offline-only recovery scenarios. Every decision stays HOLD."""
import ast
from dataclasses import replace
import json
from pathlib import Path
import unittest

from sender_review.protective_recovery_simulator_offline import (
    RecoveryReview, SimulatedObservation, SimulatedOrder,
    review_close_and_recovery_offline,
)

ACCOUNT = "0x" + "1" * 40
NONCE = "a" * 32
REF = "b" * 32
CLOID = "0x" + "c" * 32


def close(**changes):
    body = {
        "version": 1, "action": "protective_close", "side": "long",
        "coin": "SOL", "request_nonce": NONCE, "position_ref": REF,
        "close_size": "0.16", "observed_position_size": "0.20",
        "exit_reason": "trailing_protection", "reduce_only": True,
    }
    body.update(changes)
    return json.dumps(body).encode()


def position(**changes):
    return replace(SimulatedObservation(
        bot="daily", account=ACCOUNT, coin="SOL", side="long",
        position_ref=REF, position_size="0.20", position_age_seconds=1,
        owned_by_requesting_bot=True, fence=4,
    ), **changes)


def order(**changes):
    return replace(SimulatedOrder(
        nonce=NONCE, account=ACCOUNT, coin="SOL", side="long", fence=4,
        cloid=CLOID, status="unknown_ack",
        submitted_size="0.16", cumulative_fill="0", remaining_size="0.16",
    ), **changes)


def assess(**changes):
    values = dict(body=close(), fixture_bot="daily", position=position(),
                  order=order(), expected_account=ACCOUNT, expected_fence=4)
    values.update(changes)
    return review_close_and_recovery_offline(**values)


class ProtectiveRecoveryOfflineTests(unittest.TestCase):
    def assert_hold(self, result: RecoveryReview):
        self.assertEqual(result.state, "HOLD")
        self.assertFalse(result.runtime_identity_authenticated)
        self.assertFalse(result.exchange_snapshot_verified)
        self.assertFalse(result.position_ownership_verified)
        self.assertFalse(result.nonce_reserved)
        self.assertFalse(result.fence_released)
        self.assertFalse(result.retry_authorized)
        self.assertFalse(result.close_authorized)
        self.assertFalse(result.submit_authorized)
        self.assertFalse(result.signing_enabled)

    def test_unknown_ack_blocks_all_resends_and_release(self):
        result=assess()
        self.assertEqual(result.reason,"unknown-ack-permanent-hold")
        self.assertEqual(result.simulated_remaining,"0.16")
        self.assertTrue(result.fixture_matched)
        self.assert_hold(result)

    def test_partial_fills_are_not_flatness_or_retry_permission(self):
        for filled,remaining in (("0.04","0.12"),("0.15","0.01")):
            with self.subTest(filled=filled):
                result=assess(order=order(
                    status="partial",cumulative_fill=filled,
                    remaining_size=remaining))
                self.assertEqual(result.reason,"partial-fill-needs-independent-reconciliation")
                self.assertEqual(result.simulated_remaining,remaining)
                self.assert_hold(result)
        for bad in (
            order(status="partial",cumulative_fill="0",remaining_size="0.16"),
            order(status="partial",cumulative_fill="0.16",remaining_size="0"),
            order(status="partial",cumulative_fill="0.20",remaining_size="0"),
        ):
            self.assert_hold(assess(order=bad))
            self.assertFalse(assess(order=bad).fixture_matched)

    def test_full_fill_cancellation_open_and_not_sent_stay_hold(self):
        cases=(
            (order(status="filled",cumulative_fill="0.16",remaining_size="0"),
             "fixture-filled-still-no-release"),
            (order(status="canceled",cumulative_fill="0.04",remaining_size="0.12"),
             "fixture-canceled-still-no-release"),
            (order(status="open"),"open-order-already-outstanding"),
            (order(status="not_sent"),"not-sent-is-not-proof-of-safe-retry"),
        )
        for fixture,expected in cases:
            with self.subTest(expected=expected):
                result=assess(order=fixture)
                self.assertEqual(result.reason,expected)
                self.assertTrue(result.fixture_matched)
                self.assert_hold(result)

    def test_stale_positions_and_wrong_ownership_never_authorize_close(self):
        cases=(
            position(position_age_seconds=11),
            position(position_age_seconds=-1),
            position(owned_by_requesting_bot=False),
            position(bot="intraday"),
            position(account="0x"+"2"*40),
            position(coin="AVAX"),
            position(side="short"),
            position(position_ref="d"*32),
            position(fence=5),
            position(position_size="0.14"),
            position(position_size="0.15"),
            position(active_nonce="e"*32),
        )
        for fixture in cases:
            with self.subTest(fixture=fixture):
                result=assess(position=fixture)
                self.assertFalse(result.fixture_matched)
                self.assert_hold(result)

    def test_duplicate_nonce_and_competing_order_are_denied(self):
        self.assertEqual(assess(seen_nonces=frozenset({NONCE})).reason,
                         "duplicate-request-nonce")
        for fixture in (
            order(nonce="d"*32),order(fence=5),
            order(account="0x"+"2"*40),order(coin="LINK"),
            order(side="short"),order(cloid="not-a-cloid"),
        ):
            with self.subTest(fixture=fixture):
                result=assess(order=fixture)
                self.assertEqual(result.reason,"mismatched-order-provenance")
                self.assert_hold(result)

    def test_contradictory_fill_evidence_and_unknown_status_fail_closed(self):
        cases=(
            order(cumulative_fill="0.05",remaining_size="0.10"),
            order(cumulative_fill="NaN"),
            order(cumulative_fill="-1"),
            order(submitted_size="0.20",remaining_size="0.20"),
            order(status="filled",cumulative_fill="0.04",remaining_size="0.12"),
            order(status="partial",cumulative_fill="0",remaining_size="0.16"),
            order(status="alien"),
        )
        for fixture in cases:
            with self.subTest(fixture=fixture):
                self.assert_hold(assess(order=fixture))
                self.assertFalse(assess(order=fixture).fixture_matched)

    def test_invalid_close_and_missing_order_are_hold(self):
        cases=(close(close_size="0.21"),close(reduce_only=False),
               close(position_ref="0"*32),close(action="close"))
        for payload in cases:
            self.assert_hold(assess(body=payload))
        missing=assess(order=None)
        self.assertEqual(missing.reason,"missing-order-provenance")
        self.assert_hold(missing)

    def test_independent_fixtures_all_bots_have_no_authority(self):
        for bot in ("daily","intraday","aggressive"):
            result=assess(fixture_bot=bot,position=position(bot=bot))
            self.assertEqual(result.reason,"unknown-ack-permanent-hold")
            self.assert_hold(result)

    def test_module_has_no_network_db_signer_imports(self):
        source=Path(__file__).with_name(
            "protective_recovery_simulator_offline.py").read_text("utf-8")
        modules=set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node,ast.Import):
                modules.update(a.name for a in node.names)
            if isinstance(node,ast.ImportFrom):
                modules.add(node.module)
        self.assertEqual(modules,{
            "dataclasses","decimal","json",
            "sender_review.proposed_intent_interfaces_offline",
        })


if __name__=="__main__":
    unittest.main()
