"""Bridge untouched legacy sizing to the strict offline S1 request envelope.

Only AST-extracted legacy execute_trade code runs with the inert capture
adapter. The bridge never imports/runs a full trading bot, signer, SDK,
network client, database, or actual request transport. Every outcome HOLD.
"""
from copy import copy
import hashlib
import json
import unittest

from sender_review.runner_entry_request_handoff_review import (
    prepare_captured_legacy_entry_handoff_review_only,
)
from sender_review.test_legacy_order_capture_preview import (
    LegacyCapturePreviewTests,
)
from sender_review.test_remote_request_boundary_offline import (
    OfflineRemoteRequestBoundaryTests, NOW,
)
from sender_review.remote_request_boundary_offline import (
    inspect_signed_remote_request_offline,
)


class CapturedLegacyEntryHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OfflineRemoteRequestBoundaryTests.setUpClass()
        cls.fixture = OfflineRemoteRequestBoundaryTests()
        cls.keys = OfflineRemoteRequestBoundaryTests.keys
        cls.legacy = LegacyCapturePreviewTests()

    def test_three_bot_two_direction_entry_sizing_is_exact_and_never_sent(self):
        for bot in ("daily", "intraday", "aggressive"):
            for action in ("open_long", "open_short"):
                with self.subTest(bot=bot, action=action):
                    result, capture = self.legacy.run_legacy(bot, action)
                    self.assertEqual(result["status"], "NO_SEND_REVIEW_ONLY")
                    self.assertEqual(result["exchange_response"]["status"], "error")
                    handoff = prepare_captured_legacy_entry_handoff_review_only(
                        capture=capture,
                        candidate_runner_jwt=self.fixture.token(bot),
                    )
                    self.assertEqual(
                        handoff.state,
                        "unsigned_authority_runner_handoff_review_only_HOLD",
                    )
                    self.assertEqual(handoff.method, "POST")
                    self.assertEqual(handoff.path, "/v1/review-only/entry-intents")
                    self.assertEqual(handoff.body, capture.proposed_body)
                    self.assertEqual(handoff.body_sha256,
                                     hashlib.sha256(capture.proposed_body).hexdigest())
                    self.assertEqual(handoff.fixture_bot, bot)
                    self.assertFalse(handoff.submit_authorized)
                    self.assertFalse(handoff.signing_enabled)
                    self.assertFalse(handoff.close_authorized)
                    self.assertNotIn("Bearer ", repr(handoff))
                    inspected = inspect_signed_remote_request_offline(
                        method=handoff.method, path=handoff.path,
                        headers=handoff.headers, body=handoff.body,
                        trusted_fixture_keys=self.keys,
                        fixture_now_seconds=NOW,
                    )
                    self.assertEqual(inspected.state, "signed_fixture_review_only")
                    self.assertFalse(inspected.runtime_identity_authenticated)
                    self.assertFalse(inspected.submit_authorized)

    def test_corrupted_capture_never_produces_envelope(self):
        _, original = self.legacy.run_legacy("daily")
        variants = [
            {"proposed_action": "open_short"},
            {"expected_action": "open_short"},
            {"observed_coin": "AVAX"},
            {"fixture_nonce": "b" * 32},
            {"observed_leverage": 3},
            {"calls": ["entry_proposal_only"]},
            {"signing_enabled": True},
            {"submit_authorized": True},
            {"close_authorized": True},
            {"leverage_authorized": True},
            {"fixture_parent_position_ref": "b" * 32},
            {"proposed_body": b"not json"},
            {"proposed_body": json.dumps({
                **json.loads(original.proposed_body), "coin": "AVAX",
            }).encode()},
            {"proposed_body": original.proposed_body + b" "},
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                # Simulate post-construction tampering; __post_init__ correctly
                # refuses invalid scopes when constructing fresh captures.
                capture = copy(original)
                for key, value in changes.items():
                    setattr(capture, key, value)
                result = prepare_captured_legacy_entry_handoff_review_only(
                    capture=capture,
                    candidate_runner_jwt=self.fixture.token("daily"),
                )
                self.assertEqual(result.state, "hold")
                self.assertIsNone(result.body)
                self.assertIsNone(result.headers)
                self.assertFalse(result.submit_authorized)

    def test_fake_token_and_pyramid_are_not_authorization(self):
        _, original = self.legacy.run_legacy("aggressive", "pyramid_long",
                                             parent_ref="b" * 32)
        rejected = prepare_captured_legacy_entry_handoff_review_only(
            capture=original, candidate_runner_jwt=self.fixture.token("aggressive"),
        )
        self.assertEqual(rejected.state, "hold")
        self.assertIsNone(rejected.body)

        _, entry = self.legacy.run_legacy("daily")
        for token in (None, "", "bad"):
            with self.subTest(token=token):
                result = prepare_captured_legacy_entry_handoff_review_only(
                    capture=entry, candidate_runner_jwt=token,
                )
                self.assertEqual(result.state, "hold")
                self.assertIsNone(result.headers)
                self.assertFalse(result.request_authorized)


if __name__ == "__main__":
    unittest.main()
