import base64
import hashlib
import hmac
import json
import unittest

from trusted_reconciler_gateway_jwt_staging import verify_staging_jwt

KEY = b"staging-test-only-secret-key-32-bytes-minimum"

def token(payload, *, key=KEY, algorithm="HS256"):
    def encode(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    header = encode({"alg": algorithm, "typ": "JWT"})
    body = encode(payload)
    signing = header + "." + body
    sig = base64.urlsafe_b64encode(
        hmac.new(key, signing.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return signing + "." + sig

CLAIMS = {"sub": "worker", "iss": "trusted-staging", "aud": "staging-reconciler",
          "scope": "reconciler:position-write", "iat": 90, "nbf": 90, "exp": 200}

class JwtTests(unittest.TestCase):
    def verify(self, value):
        return verify_staging_jwt(value, KEY, issuer="trusted-staging",
                                  audience="staging-reconciler", now=100)

    def test_valid_signature(self):
        self.assertEqual(self.verify(token(CLAIMS)).subject, "worker")

    def test_invalid_signature(self):
        with self.assertRaises(PermissionError):
            self.verify(token(CLAIMS, key=b"wrong-key-not-used-by-the-gateway-000"))

    def test_duplicate_claim_fields_rejected(self):
        def enc(value):
            return base64.urlsafe_b64encode(value.encode()).rstrip(b"=").decode()
        header = enc('{"alg":"HS256","typ":"JWT"}')
        body = enc('{"sub":"worker","iss":"trusted-staging","aud":"staging-reconciler",'
                   '"scope":"reconciler:position-write","iat":90,"nbf":90,'
                   '"exp":200,"exp":999999}')
        signing = header + "." + body
        sig = base64.urlsafe_b64encode(
            hmac.new(KEY, signing.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        with self.assertRaises(PermissionError):
            self.verify(signing + "." + sig)

    def test_algorithm_restriction(self):
        with self.assertRaises(PermissionError):
            self.verify(token(CLAIMS, algorithm="none"))

    def test_reject_bad_claims(self):
        for changed in ({"aud": "executor"}, {"iss": "other"}, {"exp": 100},
                        {"nbf": 101}, {"iat": 101}, {"scope": "executor:reserve"},
                        {"sub": ""}):
            with self.subTest(changed=changed):
                with self.assertRaises(PermissionError):
                    self.verify(token({**CLAIMS, **changed}))

if __name__ == "__main__":
    unittest.main()
