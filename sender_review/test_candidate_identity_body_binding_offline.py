"""Mock-only identity-to-exact-body integration; absolutely no trade GO."""
from dataclasses import replace
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from sender_review.candidate_identity_body_binding_offline import (
    inspect_candidate_identity_body_binding_offline,
)
from sender_review.github_oidc_fixed_origin_transport_candidate import (
    FixedOriginPublicKeysCandidate,
)
from sender_review.test_remote_request_boundary_offline import (
    OfflineRemoteRequestBoundaryTests, NOW,
)
from sender_review.test_offline_oidc_identity_fixture import SignedOidcFixtureTests


class CandidateIdentityBodyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OfflineRemoteRequestBoundaryTests.setUpClass()
        cls.fixture = OfflineRemoteRequestBoundaryTests()
        cls.keys = FixedOriginPublicKeysCandidate(
            state="candidate_fixed_origin_keys_review_only_HOLD",
            keyset_sha256="a" * 64,
            public_key_count=1,
            candidate_public_keys=SignedOidcFixtureTests.keys,
        )

    def check(self, *, bot="daily", token=None, body=None, keys=None, now=NOW):
        return inspect_candidate_identity_body_binding_offline(
            token=self.fixture.token(bot) if token is None else token,
            request_body=self.fixture.body() if body is None else body,
            candidate_keys=self.keys if keys is None else keys,
            fixture_now_seconds=now,
        )

    def deny_authority(self, result):
        for key in (
            "jwt_cryptographically_signs_body", "bearer_replay_prevented",
            "independently_verified_request_origin",
            "runtime_identity_authenticated", "exact_body_authenticated",
            "replay_consumed", "durable_fence_reserved", "journal_recorded",
            "submit_authorized", "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, key), False, key)

    def test_all_three_signed_fake_bots_and_exact_body_hash_stay_hold(self):
        body = self.fixture.body()
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                report = self.check(bot=bot, body=body)
                self.assertEqual(report.state, "SYNTHETIC_IDENTITY_EXACT_BODY_HOLD")
                self.assertEqual(report.candidate_bot, bot)
                self.assertTrue(report.fake_identity_and_exact_body_reviewed)
                self.assertEqual(report.body_sha256, hashlib.sha256(body).hexdigest())
                self.assertEqual(report.candidate_keyset_sha256, "a" * 64)
                self.assertEqual(len(report.candidate_jti_sha256), 64)
                self.assertNotIn(self.fixture.token(bot), repr(report))
                self.deny_authority(report)

    def test_same_bearer_token_different_valid_bodies_never_prove_origin(self):
        token = self.fixture.token()
        first = self.check(token=token, body=self.fixture.body())
        second = self.check(token=token, body=self.fixture.body(
            coin="AVAX", request_nonce="b"*32,
        ))
        self.assertTrue(first.fake_identity_and_exact_body_reviewed)
        self.assertTrue(second.fake_identity_and_exact_body_reviewed)
        self.assertEqual(first.candidate_jti_sha256, second.candidate_jti_sha256)
        self.assertEqual(first.token_sha256, second.token_sha256)
        self.assertNotEqual(first.body_sha256, second.body_sha256)
        self.assertNotEqual(first.request_nonce_sha256, second.request_nonce_sha256)
        self.deny_authority(first)
        self.deny_authority(second)

    def test_changed_body_approved_flag_and_invalid_schema_hold(self):
        for body in (
            b"{}", b'{"submit_authorized":true}',
            self.fixture.body(submit_authorized=True),
            self.fixture.body(coin="sol-invalid"),
            b"",
        ):
            with self.subTest(body=body):
                report = self.check(body=body)
                self.assertEqual(report.state, "HOLD")
                self.assertFalse(report.fake_identity_and_exact_body_reviewed)
                self.deny_authority(report)

    def test_forged_expired_wrong_workflow_and_untrusted_keys_hold(self):
        cases = (
            {"token": self.fixture.token(repository="attacker/crypto-yall")},
            {"token": self.fixture.token(event_name="pull_request_target")},
            {"token": self.fixture.token(exp=NOW-1)},
            {"token": "not.a.token"},
            {"keys": FixedOriginPublicKeysCandidate()},
            {"keys": replace(self.keys, keyset_sha256="Z"*64)},
            {"keys": replace(self.keys, submit_authorized=True)},
            {"keys": replace(self.keys, public_key_count=2)},
            {"keys": replace(self.keys, candidate_public_keys={})},
        )
        for changes in cases:
            with self.subTest(changes=str(changes)[:70]):
                result = self.check(**changes)
                self.assertEqual(result.state, "HOLD")
                self.deny_authority(result)

    def test_no_network_database_signer_or_real_identity_dependency(self):
        base = Path(__file__).resolve().parent
        source = (base / "candidate_identity_body_binding_offline.py").read_text("utf-8")
        import ast
        imports = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imports.update(n.name for n in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {
            "dataclasses", "hashlib", "json",
            "sender_review.github_oidc_fixed_origin_transport_candidate",
            "sender_review.offline_oidc_identity_fixture",
            "sender_review.remote_request_boundary_offline",
            "sender_review.request_contract",
        })
        with patch(
            "sender_review.github_oidc_fixed_origin_transport_candidate."
            "inspect_fixed_origin_public_keys_candidate",
            side_effect=AssertionError("network candidate must not run"),
        ):
            self.deny_authority(self.check())


if __name__ == "__main__":
    unittest.main()
