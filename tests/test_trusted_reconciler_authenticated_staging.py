import base64
import hashlib
import hmac
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from trusted_reconciler_authenticated_staging import (
    reconcile_entry_with_token, reconcile_release_with_token)

KEY = b"offline-only-test-signing-key-32-bytes-or-more"

def signed_token(*, scope="reconciler:position-write", exp=200, key=KEY):
    def enc(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    head = enc({"alg": "HS256", "typ": "JWT"})
    body = enc({"sub": "reconciler", "iss": "staging-idp",
                "aud": "staging-gateway", "scope": scope,
                "iat": 90, "nbf": 90, "exp": exp})
    signed = head + "." + body
    sig = base64.urlsafe_b64encode(hmac.new(key, signed.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return signed + "." + sig

AUTH = dict(signing_key=KEY, issuer="staging-idp",
            audience="staging-gateway", now=100)
ENTRY = dict(coin="SOL", bot="intraday", token="durable-token",
             order_id=17, order_start_ms=99000, clock=lambda: 100)
OWNER = dict(coin="SOL", bot="intraday", token="durable-token",
             clock=lambda: 100)

class AuthenticatedStagingTests(unittest.TestCase):
    def test_rejects_invalid_tokens_before_exchange_or_database(self):
        for candidate in ("not.a.jwt", signed_token(scope="executor:reserve"),
                          signed_token(exp=100),
                          signed_token(key=b"different-signing-key-for-test-1234")):
            with self.subTest(candidate=candidate[:20]):
                with patch("trusted_reconciler_service_staging.reconcile_entry") as evidence:
                    calls = []
                    with self.assertRaises(PermissionError):
                        reconcile_entry_with_token(None, None,
                            lambda *a: calls.append(a), auth_token=candidate,
                            **AUTH, **ENTRY)
                    evidence.assert_not_called()
                    self.assertEqual(calls, [])

    def test_signed_entry_with_unavailable_evidence_never_writes(self):
        calls = []
        with patch("trusted_reconciler_service_staging.reconcile_entry",
                   side_effect=ConnectionError("exchange unavailable")):
            with self.assertRaises(ConnectionError):
                reconcile_entry_with_token(None, None,
                    lambda *a: calls.append(a) or True,
                    auth_token=signed_token(), **AUTH, **ENTRY)
        self.assertEqual(calls, [])

    def test_signed_entry_reaches_existing_verified_handoff(self):
        calls = []
        with patch("trusted_reconciler_service_staging.reconcile_entry",
                   return_value=SimpleNamespace(action="handoff_candidate")):
            result = reconcile_entry_with_token(None, None,
                lambda name, data: calls.append(name) or True,
                auth_token=signed_token(), **AUTH, **ENTRY)
        self.assertTrue(result.confirmed)
        self.assertEqual(calls, ["record_bot_position_owner"])

    def test_release_denied_before_exchange(self):
        with patch("trusted_reconciler_service_staging.release_verified") as evidence:
            with self.assertRaises(PermissionError):
                reconcile_release_with_token(None, None, lambda *a: True,
                    auth_token=signed_token(scope="executor:reserve"), **AUTH, **OWNER)
            evidence.assert_not_called()

    def test_signed_entry_rejects_non_intraday_bot(self):
        calls = []
        with patch("trusted_reconciler_service_staging.reconcile_entry") as evidence:
            for bot in ("aggressive", "daily"):
                with self.subTest(bot=bot):
                    result = reconcile_entry_with_token(None, None,
                        lambda *a: calls.append(a) or True,
                        auth_token=signed_token(), **AUTH, **{**ENTRY, "bot": bot})
                    self.assertFalse(result.confirmed)
            evidence.assert_not_called()
        self.assertEqual(calls, [])

    def test_signed_release_rejects_non_intraday_bot(self):
        calls = []
        with patch("trusted_reconciler_service_staging.release_verified") as evidence:
            for bot in ("aggressive", "daily"):
                with self.subTest(bot=bot):
                    result = reconcile_release_with_token(None, None,
                        lambda *a: calls.append(a) or True,
                        auth_token=signed_token(), **AUTH, **{**OWNER, "bot": bot})
                    self.assertFalse(result.confirmed)
            evidence.assert_not_called()
        self.assertEqual(calls, [])

    def test_signed_release_can_only_use_verified_release_path(self):
        with patch("trusted_reconciler_service_staging.release_verified",
                   return_value=True) as verified:
            result = reconcile_release_with_token(None, None,
                lambda *a: True, auth_token=signed_token(), **AUTH, **OWNER)
        self.assertTrue(result.confirmed)
        verified.assert_called_once()

    def test_signed_release_still_holds_if_exchange_disagrees(self):
        with patch("trusted_reconciler_service_staging.release_verified",
                   return_value=False) as evidence:
            result = reconcile_release_with_token(None, None,
                lambda *a: True, auth_token=signed_token(), **AUTH, **OWNER)
        self.assertFalse(result.confirmed)
        evidence.assert_called_once()

if __name__ == "__main__":
    unittest.main()
