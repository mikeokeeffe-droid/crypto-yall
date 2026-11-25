"""Offline worker request-fixture checks; never imports a trading executor."""
import ast
import json
from pathlib import Path
import unittest

from sender_review.worker_intent_fixture_builder_offline import (
    build_worker_intent_fixture_offline,
)
from sender_review.proposed_intent_interfaces_offline import (
    inspect_proposed_intent_offline,
)

NONCE = "a" * 32
REF = "b" * 32

def build(bot="daily", action="open_long", **fields):
    data = dict(
        fixture_bot=bot, action=action, coin="SOL",
        side="long", request_nonce=NONCE,
    )
    data.update(fields)
    return build_worker_intent_fixture_offline(**data)

class WorkerIntentFixtureBuilderTests(unittest.TestCase):
    def assert_no_authority(self, result):
        for name in (
            "runtime_identity_authenticated", "account_scope_verified",
            "exchange_state_verified", "request_authorized",
            "submit_authorized", "close_authorized",
            "leverage_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, name), False)

    def test_three_bot_entries_have_canonical_inert_bytes(self):
        for bot in ("daily", "intraday", "aggressive"):
            for action, side in (("open_long", "long"), ("open_short", "short")):
                with self.subTest(bot=bot, action=action):
                    result = build(bot, action, side=side,
                                   rounded_size="0.16", requested_leverage=2)
                    self.assertEqual(result.state, "fixture_body_review_only_HOLD")
                    self.assert_no_authority(result)
                    self.assertEqual(
                        result.fixture_body,
                        json.dumps(json.loads(result.fixture_body),
                                   sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=True).encode("ascii"),
                    )
                    self.assertEqual(
                        inspect_proposed_intent_offline(
                            body=result.fixture_body, fixture_bot=bot
                        ).state, "parsed_review_only_HOLD"
                    )

    def test_pyramid_close_and_leverage_are_untrusted_proposals(self):
        cases = (
            ("aggressive", "pyramid_long", {
                "rounded_size": "0.02", "requested_leverage": 2,
                "parent_position_ref": REF,
            }),
            ("intraday", "protective_close", {
                "close_size": "0.10", "observed_position_size": "0.20",
                "position_ref": REF, "exit_reason": "profit_floor",
                "reduce_only": True,
            }),
            ("daily", "request_leverage", {
                "requested_leverage": 2, "parent_position_ref": REF,
            }),
        )
        for bot, action, fields in cases:
            with self.subTest(action=action):
                result = build(bot, action, **fields)
                self.assertEqual(result.state, "fixture_body_review_only_HOLD")
                self.assertIsInstance(result.fixture_body, bytes)
                self.assert_no_authority(result)
        denied = build("intraday", "pyramid_long",
                       rounded_size="0.02", requested_leverage=2,
                       parent_position_ref=REF)
        self.assertEqual(denied.state, "hold")
        self.assertIsNone(denied.fixture_body)

    def test_invalid_and_authority_claims_fail_closed(self):
        good = dict(rounded_size="0.16", requested_leverage=2)
        cases = (
            {"account": "0x" + "1" * 40},
            {"submit_authorized": True},
            {"private_key": "secret"},
            {"rounded_size": "-1"},
            {"rounded_size": "1e3"},
            {"requested_leverage": True},
            {"requested_leverage": 6},
            {"request_nonce": "invalid"},
            {"coin": "sol"},
            {"side": "short"},
            {"fixture_bot": "unauthenticated"},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                result = build(**(good | changes))
                self.assertEqual(result.state, "hold")
                self.assertIsNone(result.fixture_body)
                self.assert_no_authority(result)

    def test_source_imports_no_io_or_signing(self):
        source = Path(__file__).with_name(
            "worker_intent_fixture_builder_offline.py"
        ).read_text("utf-8")
        imports = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imports.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {
            "dataclasses", "json",
            "sender_review.proposed_intent_interfaces_offline",
        })

if __name__ == "__main__":
    unittest.main()
