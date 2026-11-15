"""No-network authentication boundary tests using disposable signed JWTs only."""
import hashlib
import json
import unittest
from dataclasses import replace

from sender_review.remote_request_boundary_offline import (
    OFFLINE_REQUEST_POLICY, _WORKFLOWS, inspect_signed_remote_request_offline,
)
from sender_review.test_offline_oidc_identity_fixture import SignedOidcFixtureTests, NOW

class OfflineRemoteRequestBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SignedOidcFixtureTests.setUpClass()
        cls.keys = SignedOidcFixtureTests.keys
        cls.fixture = SignedOidcFixtureTests()

    @staticmethod
    def body(**changes):
        data = {
            "version": 1, "action": "open_long", "side": "long",
            "coin": "SOL", "rounded_size": "0.16",
            "requested_leverage": 2, "request_nonce": "a" * 32,
        }
        data.update(changes)
        return json.dumps(data, separators=(",", ":")).encode()

    def token(self, bot="daily", **changes):
        # The existing signed-fixture helper uses a different example policy;
        # issue an RSA-signed fake JWT with the exact proposed repo policy.
        import base64
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        def enc(obj):
            b = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
            return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
        claims = {
            "iss": "https://token.actions.githubusercontent.com",
            "aud": OFFLINE_REQUEST_POLICY.audience,
            "repository": OFFLINE_REQUEST_POLICY.repository,
            "repository_id": OFFLINE_REQUEST_POLICY.repository_id,
            "ref": OFFLINE_REQUEST_POLICY.ref,
            "sub": OFFLINE_REQUEST_POLICY.subject,
            "event_name": "workflow_dispatch",
            "workflow_ref": next(x for x, b in _WORKFLOWS if b == bot),
            "jti": "fixture-jti-001",
            "sha": "a" * 40, "run_id": "123456789", "run_attempt": "1",
            "nbf": NOW-30, "iat": NOW-20, "exp": NOW+120,
        }
        claims.update(changes)
        message = enc({"alg": "RS256", "typ": "JWT", "kid": "ci-fixture"}) + "." + enc(claims)
        signature = SignedOidcFixtureTests.key.sign(
            message.encode(), padding.PKCS1v15(), hashes.SHA256()
        )
        return message + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    def check(self, token=None, body=None, headers=None, method="POST",
              path="/v1/review-only/entry-intents"):
        token = token if token is not None else self.token()
        body = body if body is not None else self.body()
        headers = headers if headers is not None else [
            ("Authorization", "Bearer " + token),
            ("Content-Type", "application/json"),
        ]
        return inspect_signed_remote_request_offline(
            method=method, path=path, headers=headers, body=body,
            trusted_fixture_keys=self.keys, fixture_now_seconds=NOW,
        )

    def test_three_workflows_accepted_as_fixture_only_no_trading_authority(self):
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                r = self.check(token=self.token(bot))
                self.assertEqual(r.state, "signed_fixture_review_only")
                self.assertEqual(r.fixture_bot, bot)
                self.assertTrue(r.fixture_signature_checked)
                self.assertEqual(r.request_sha256, hashlib.sha256(self.body()).hexdigest())
                for attr in (
                    "runtime_identity_authenticated", "tls_peer_authenticated",
                    "replay_consumed", "account_scope_verified",
                    "request_authorized", "submit_authorized", "close_authorized",
                    "signing_enabled",
                ):
                    self.assertFalse(getattr(r, attr), attr)

    def test_identity_and_time_rejections(self):
        bad_claims = (
            {"repository": "attacker/crypto-yall"},
            {"repository_id": "000"},
            {"aud": "wrong"},
            {"iss": "https://evil.example"},
            {"sub": "repo:attacker:ref:refs/heads/main"},
            {"ref": "refs/heads/other"},
            {"event_name": "pull_request_target"},
            {"workflow_ref": "mikeokeeffe-droid/crypto-yall/.github/workflows/other.yml@refs/heads/main"},
            {"nbf": NOW + 100},
            {"exp": NOW},
            {"run_attempt": 1},
        )
        for claims in bad_claims:
            with self.subTest(claims=claims):
                self.assertEqual(self.check(token=self.token(**claims)).state, "hold")

    def test_duplicate_authorization_headers_and_unknown_headers_refused(self):
        t = self.token()
        cases = (
            [("Authorization", "Bearer "+t), ("authorization", "Bearer "+t)],
            [("Authorization", "Bearer "+t), ("X-Account", "test")],
            [("Authorization", "Bearer "+t), ("Content-Type", "text/plain")],
            [("Authorization", "Bearer "+t), ("Content-Type", "application/json"),
             ("X-Trusted-Bot", "daily")],
            [("Authorization", "Bearer "+t+"\r\nX-Admin: true"),
             ("Content-Type", "application/json")],
        )
        for h in cases:
            with self.subTest(headers=h):
                self.assertEqual(self.check(headers=h).state, "hold")

    def test_method_path_and_caller_authority_deny(self):
        self.assertEqual(self.check(method="GET").state, "hold")
        self.assertEqual(self.check(path="/v1/execute").state, "hold")
        for changes in (
            {"bot": "daily"},
            {"account": "0x" + "1"*40},
            {"submit_authorized": True},
            {"action": "close", "side": "long"},
            {"action": "market_open"},
        ):
            with self.subTest(changes=changes):
                r = self.check(body=self.body(**changes))
                self.assertNotEqual(r.state, "signed_fixture_review_only")
                self.assertFalse(r.submit_authorized)

    def test_no_network_or_operational_service_imports(self):
        import ast
        from pathlib import Path
        source = Path(__file__).with_name("remote_request_boundary_offline.py").read_text("utf-8")
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module)
        self.assertEqual(set(imports), {
            "dataclasses", "hashlib",
            "sender_review.offline_oidc_identity_fixture",
            "sender_review.request_contract",
        })


if __name__ == "__main__":
    unittest.main()
