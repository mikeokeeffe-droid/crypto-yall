"""No-send integration of existing bot request builder and OIDC review."""
import hashlib
import unittest
from sender_review.runner_entry_request_handoff_review import (
    prepare_runner_entry_handoff_review_only,
)
from sender_review.remote_request_boundary_offline import (
    inspect_signed_remote_request_offline,
)
from sender_review.test_remote_request_boundary_offline import (
    OfflineRemoteRequestBoundaryTests, NOW,
)


class RunnerEntryHandoffReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OfflineRemoteRequestBoundaryTests.setUpClass()
        cls.fixture = OfflineRemoteRequestBoundaryTests()
        cls.keys = OfflineRemoteRequestBoundaryTests.keys

    def prepare(self, bot="daily", **changes):
        values = dict(
            candidate_runner_jwt=self.fixture.token(bot), fixture_bot=bot,
            action="open_long", coin="SOL", side="long",
            request_nonce="a" * 32, rounded_size="0.16",
            requested_leverage=2,
        )
        values.update(changes)
        return prepare_runner_entry_handoff_review_only(**values)

    def denied(self, result):
        for name in (
            "identity_authenticated", "server_authenticated",
            "nonce_reserved", "journal_recorded", "account_scope_verified",
            "exchange_state_verified", "request_authorized",
            "submit_authorized", "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, name), False, name)

    def test_all_existing_bot_entry_shapes_reach_only_offline_review(self):
        for bot in ("daily", "intraday", "aggressive"):
            for action, side in (("open_long", "long"), ("open_short", "short")):
                with self.subTest(bot=bot, action=action):
                    result = self.prepare(bot, action=action, side=side)
                    self.assertEqual(
                        result.state,
                        "unsigned_authority_runner_handoff_review_only_HOLD",
                    )
                    self.assertEqual(result.method, "POST")
                    self.assertEqual(result.path,
                                     "/v1/review-only/entry-intents")
                    self.assertEqual(
                        result.body_sha256,
                        hashlib.sha256(result.body).hexdigest(),
                    )
                    self.assertNotIn("Bearer ", repr(result))
                    self.denied(result)
                    review = inspect_signed_remote_request_offline(
                        method=result.method, path=result.path,
                        headers=result.headers, body=result.body,
                        trusted_fixture_keys=self.keys,
                        fixture_now_seconds=NOW,
                    )
                    self.assertEqual(review.state,
                                     "signed_fixture_review_only")
                    self.assertEqual(review.fixture_bot, bot)
                    self.assertFalse(review.request_authorized)
                    self.assertFalse(review.submit_authorized)

    def test_wrong_identity_and_unsupported_operations_hold(self):
        cases = (
            {"candidate_runner_jwt": "bad"},
            {"candidate_runner_jwt": ""},
            {"candidate_runner_jwt": None},
            {"fixture_bot": "untrusted"},
            {"action": "protective_close"},
            {"action": "pyramid_long"},
            {"action": "request_leverage"},
            {"side": "short"},
            {"rounded_size": "-1"},
            {"requested_leverage": True},
            {"requested_leverage": 6},
            {"request_nonce": "invalid"},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                result = self.prepare(**changes)
                self.assertEqual(result.state, "hold")
                self.assertIsNone(result.body)
                self.assertIsNone(result.headers)
                self.denied(result)

    def test_fake_token_shape_has_no_authenticated_authority(self):
        fake = "a" * 40 + "." + "b" * 80 + "." + "c" * 80
        result = self.prepare(candidate_runner_jwt=fake)
        self.assertEqual(
            result.state, "unsigned_authority_runner_handoff_review_only_HOLD"
        )
        self.assertNotIn(fake, repr(result))
        self.denied(result)
        rejected = inspect_signed_remote_request_offline(
            method=result.method, path=result.path, headers=result.headers,
            body=result.body, trusted_fixture_keys=self.keys,
            fixture_now_seconds=NOW,
        )
        self.assertEqual(rejected.state, "hold")
        self.assertFalse(rejected.submit_authorized)


if __name__ == "__main__":
    unittest.main()
