"""Only disposable RSA test keys. Does not authenticate real GitHub Actions."""
import base64
from dataclasses import replace
import json
import unittest

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes

from sender_review.offline_oidc_identity_fixture import (
    OfflineOidcTrustPolicy, verify_fixture_oidc_identity_offline,
)

REPO = "example-operator/sender-review-fixture"
REF = "refs/heads/main"
NOW = 1794700000
AUD = "urn:sender-review:testnet:request-only"
BOT_REFS = tuple((
    f"{REPO}/.github/workflows/{filename}@{REF}", bot,
) for bot, filename in (
    ("daily", "daily.yml"),
    ("intraday", "intraday.yml"),
    ("aggressive", "aggressive.yml"),
))
POLICY = OfflineOidcTrustPolicy(
    repository=REPO, repository_id="123456", audience=AUD,
    ref=REF, subject=f"repo:{REPO}:ref:{REF}",
    workflow_bot_refs=BOT_REFS,
)


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _json(value):
    return _b64(json.dumps(value, sort_keys=True,
                           separators=(",", ":")).encode())


class SignedOidcFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537,
                                           key_size=2048)
        nums = cls.key.public_key().public_numbers()
        cls.keys = {"ci-fixture": (nums.n, nums.e)}

    def token(self, bot="daily", **updates):
        claims = {
            "iss": "https://token.actions.githubusercontent.com",
            "aud": AUD, "repository": REPO, "repository_id": "123456",
            "ref": REF, "sub": POLICY.subject,
            "event_name": "schedule",
            "workflow_ref": next(name for name, b in BOT_REFS if b == bot),
            "jti": "unique-jti-001",
            "sha": "a" * 40,
            "run_id": "1234567",
            "run_attempt": "1",
            "nbf": NOW - 40, "iat": NOW - 30, "exp": NOW + 180,
        }
        claims.update(updates)
        header = {"alg": "RS256", "typ": "JWT", "kid": "ci-fixture"}
        unsigned = _json(header) + "." + _json(claims)
        signature = self.key.sign(unsigned.encode(),
                                  padding.PKCS1v15(), hashes.SHA256())
        return unsigned + "." + _b64(signature)

    def verify(self, token, policy=POLICY, keys=None, now=NOW):
        return verify_fixture_oidc_identity_offline(
            token=token, policy=policy,
            trusted_fixture_keys=self.keys if keys is None else keys,
            fixture_now_seconds=now,
        )

    def assert_no_authority(self, result):
        self.assertFalse(result.runtime_identity_authenticated)
        self.assertFalse(result.nonce_reserved)
        self.assertFalse(result.account_scope_verified)
        self.assertFalse(result.request_authorized)
        self.assertFalse(result.submit_authorized)
        self.assertFalse(result.close_authorized)

    def test_signed_three_workflow_claims_identify_fixture_bot_only(self):
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                result = self.verify(self.token(bot))
                self.assertEqual(result.state, "verified_fixture_only")
                self.assertTrue(result.fixture_signature_checked)
                self.assertEqual(result.fixture_bot, bot)
                self.assert_no_authority(result)

    def test_mutated_signature_wrong_jwks_or_unknown_key_hold(self):
        valid = self.token()
        tampered = valid[:-1] + ("A" if valid[-1] != "A" else "B")
        for candidate, keys in (
            (tampered, None),
            (valid, {}),
            (valid, {"other": self.keys["ci-fixture"]}),
            (valid, {"ci-fixture": (3, 65537)}),
        ):
            with self.subTest(keys=keys):
                result = self.verify(candidate, keys=keys)
                self.assertEqual(result.state, "hold")
                self.assert_no_authority(result)

    def test_repository_workflow_and_event_claim_spoofing_hold(self):
        alterations = (
            {"repository": "attacker/repo"},
            {"repository_id": "999"},
            {"sub": "repo:" + REPO + ":environment:prod"},
            {"aud": "malicious-service"},
            {"ref": "refs/heads/feature"},
            {"workflow_ref": REPO + "/.github/workflows/foreign.yml@" + REF},
            {"workflow_ref": BOT_REFS[0][0].replace("daily.yml", "intraday.yml")
             .replace("@" + REF, "@refs/heads/feature")},
            {"event_name": "pull_request_target"},
            {"run_attempt": 1},
            {"run_id": True},
            {"sha": "g" * 40},
            {"jti": ""},
        )
        for bad in alterations:
            with self.subTest(bad=bad):
                result = self.verify(self.token(**bad))
                self.assertEqual(result.state, "hold")
                self.assert_no_authority(result)

    def test_expiration_future_and_invalid_claim_times_hold(self):
        for bad in (
            {"exp": NOW},
            {"nbf": NOW + 20},
            {"iat": NOW + 100},
            {"exp": NOW + 900},
            {"iat": NOW - 601},
            {"iat": True},
            {"exp": None},
        ):
            with self.subTest(bad=bad):
                result = self.verify(self.token(**bad))
                self.assertEqual(result.state, "hold")
                self.assert_no_authority(result)

    def test_swapping_trust_policy_and_claims_cannot_raise_authority(self):
        token = self.token()
        policies = (
            replace(POLICY, repository_id="456"),
            replace(POLICY, audience="urn:another:audience"),
            replace(POLICY, workflow_bot_refs=BOT_REFS[:2]),
            replace(POLICY, subject="repo:" + REPO + ":environment:prod"),
            replace(POLICY, ref="refs/heads/release"),
        )
        for policy in policies:
            with self.subTest(policy=policy):
                result = self.verify(token, policy=policy)
                self.assertEqual(result.state, "hold")
                self.assert_no_authority(result)

    def test_pinned_workflow_and_source_sha_reject_unreviewed_revisions(self):
        # A valid fake RSA signature alone is insufficient to claim that
        # a reviewed workflow or source revision was used. The pins must
        # be fixed in the verifier policy, never adopted from JWT claims.
        source = "a" * 40
        workflow = "b" * 40
        policy = replace(
            POLICY, approved_source_sha=source,
            approved_workflow_sha=workflow,
        )
        valid = self.verify(
            self.token(sha=source, workflow_sha=workflow),
            policy=policy,
        )
        self.assertEqual(valid.state, "verified_fixture_only")
        self.assert_no_authority(valid)
        for changes in (
            {"sha": "c" * 40, "workflow_sha": workflow},
            {"sha": source, "workflow_sha": "c" * 40},
            {"sha": source, "workflow_sha": None},
            {"sha": source, "workflow_sha": True},
            {"sha": source},
        ):
            with self.subTest(changes=changes):
                outcome = self.verify(self.token(**changes), policy=policy)
                self.assertEqual(outcome.state, "hold")
                self.assert_no_authority(outcome)
        for bad_policy in (
            replace(policy, approved_workflow_sha="bad"),
            replace(policy, approved_source_sha="A" * 40),
            replace(policy, approved_workflow_sha=True),
        ):
            with self.subTest(policy=bad_policy):
                result = self.verify(
                    self.token(sha=source, workflow_sha=workflow),
                    policy=bad_policy,
                )
                self.assertEqual(result.state, "hold")
                self.assert_no_authority(result)

    def test_no_key_provenance_or_replay_claim_can_be_approved(self):
        # A signed and syntactically valid fixture intentionally remains
        # unapproved even when a user supplies trusted-looking values.
        first = self.verify(self.token())
        replay = self.verify(self.token())
        self.assertEqual(first.state, "verified_fixture_only")
        self.assertEqual(replay.state, "verified_fixture_only")
        self.assert_no_authority(first)
        self.assert_no_authority(replay)


if __name__ == "__main__":
    unittest.main()
