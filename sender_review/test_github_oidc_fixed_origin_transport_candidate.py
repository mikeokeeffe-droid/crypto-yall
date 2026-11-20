"""Zero-network regression checks for isolated, non-authorizing GitHub OIDC candidate."""
import base64
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from sender_review import github_oidc_fixed_origin_transport_candidate as review


def _json(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("ascii")


def _discovery(**overrides):
    payload = {
        "issuer": review._ISSUER,
        "jwks_uri": review._ISSUER + review._JWKS_PATH,
        "id_token_signing_alg_values_supported": ["RS256"],
    }
    payload.update(overrides)
    return _json(payload)


def _rsa_integer(value):
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _keys():
    # 2048-bit structural RSA test integer only. No private key or signature.
    return _json({"keys": [{
        "kty": "RSA", "kid": "fake-test-only", "use": "sig", "alg": "RS256",
        "n": _rsa_integer((1 << 2047) + 123456789),
        "e": _rsa_integer(65537),
    }]})


class _Response:
    def __init__(self, payload, status=200, headers=None):
        self.status = status
        self.payload = payload
        self.headers = headers if headers is not None else [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(payload))),
        ]

    def getheaders(self):
        return self.headers

    def read(self, limit):
        return self.payload[:limit]


class _Connection:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.closed = False

    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class FixedOriginPublicKeyCandidateTests(unittest.TestCase):
    def assert_no_authority(self, result):
        for key in (
            "runtime_identity_authenticated", "authenticated_request_body",
            "replay_consumed", "request_authorized", "submit_authorized",
            "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, key), False, key)
        self.assertIn("HOLD", result.state.upper())

    def test_fixed_metadata_then_keys_are_parsed_but_never_authorized(self):
        responses = [_discovery(), _keys()]
        with patch.object(review, "_read_fixed_public_https", side_effect=responses) as transport:
            result = review.inspect_fixed_origin_public_keys_candidate()
        self.assertEqual(result.state, "candidate_fixed_origin_keys_review_only_HOLD")
        self.assertEqual(result.keyset_sha256, hashlib.sha256(_keys()).hexdigest())
        self.assertEqual(result.public_key_count, 1)
        self.assertEqual(set(result.candidate_public_keys), {"fake-test-only"})
        self.assertEqual(transport.call_args_list[0].args,
                         (review._DISCOVERY_PATH, review._DISCOVERY_LIMIT))
        self.assertEqual(transport.call_args_list[1].args,
                         (review._JWKS_PATH, review._JWKS_LIMIT))
        self.assert_no_authority(result)

    def test_invalid_discovery_stops_before_jwks(self):
        invalid = (
            _discovery(issuer="https://attacker.example"),
            _discovery(jwks_uri="https://attacker.example/key"),
            _discovery(jwks_uri=review._ISSUER + "/alternate"),
            _discovery(id_token_signing_alg_values_supported=["HS256"]),
            _discovery(id_token_signing_alg_values_supported="RS256"),
            b'{"issuer":"one","issuer":"two"}',
            b'{"issuer":NaN}',
            b"not-json",
            b"\xff",
            b" " * (review._DISCOVERY_LIMIT + 1),
        )
        for item in invalid:
            with self.subTest(item=item[:60]):
                with patch.object(review, "_read_fixed_public_https", side_effect=[item, _keys()]) as transport:
                    result = review.inspect_fixed_origin_public_keys_candidate()
                self.assertEqual(result.state, "hold")
                self.assertEqual(transport.call_count, 1)
                self.assert_no_authority(result)

    def test_invalid_keysets_and_transport_failure_hold(self):
        cases = (b'{"keys":[]}', b'{"keys":[],"keys":[]}',
                 b'{"keys":[{"kid":"attacker"}]}', b"",
                 b" " * (review._JWKS_LIMIT + 1))
        for item in cases:
            with self.subTest(item=item[:40]):
                with patch.object(review, "_read_fixed_public_https",
                                  side_effect=[_discovery(), item]):
                    result = review.inspect_fixed_origin_public_keys_candidate()
                self.assertEqual(result.state, "hold")
                self.assert_no_authority(result)
        with patch.object(review, "_read_fixed_public_https", side_effect=OSError("not printed")):
            self.assert_no_authority(review.inspect_fixed_origin_public_keys_candidate())

    def test_transport_uses_fixed_host_normal_tls_and_no_caller_url(self):
        response = _Response(_discovery())
        connection = _Connection(response)
        with patch.object(review.ssl, "create_default_context", return_value=object()) as tls, patch.object(
            review.http.client, "HTTPSConnection", return_value=connection
        ) as factory:
            raw = review._read_fixed_public_https(review._DISCOVERY_PATH, review._DISCOVERY_LIMIT)
        self.assertEqual(raw, _discovery())
        self.assertEqual(factory.call_args.args, (review._HOST,))
        self.assertEqual(factory.call_args.kwargs["port"], 443)
        self.assertEqual(factory.call_args.kwargs["timeout"], 3.0)
        self.assertIs(factory.call_args.kwargs["context"], tls.return_value)
        self.assertEqual(connection.requests[0][0], ("GET", review._DISCOVERY_PATH))
        self.assertEqual(connection.requests[0][1]["headers"]["Accept-Encoding"], "identity")
        self.assertTrue(connection.closed)
        for invalid in ("/redirect", "https://attacker.example", review._JWKS_PATH):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                review._read_fixed_public_https(invalid, review._DISCOVERY_LIMIT)

    def test_bad_http_headers_redirects_and_limits_fail_closed(self):
        payload = _discovery()
        invalid = (
            _Response(payload, status=302),
            _Response(payload, status=503),
            _Response(payload, headers=[("Content-Type", "text/html")]),
            _Response(payload, headers=[("Content-Type", "application/json"),
                                        ("Content-Type", "application/json")]),
            _Response(payload, headers=[("Content-Type", "application/json"),
                                        ("Content-Encoding", "gzip")]),
            _Response(payload, headers=[("Content-Type", "application/json"),
                                        ("Location", "https://attacker.example")]),
            _Response(payload, headers=[("Content-Type", "application/json"),
                                        ("Transfer-Encoding", "gzip")]),
            _Response(payload, headers=[("Content-Type", "application/json"),
                                        ("Content-Length", "9999999999")]),
            _Response(payload, headers=[("Content-Type", "application/json"),
                                        ("Content-Length", "1")]),
            _Response(payload, headers=[("Content-Type", "application/json"),
                                        ("Content-Length", str(len(payload))),
                                        ("Transfer-Encoding", "chunked")]),
            _Response(b""),
            _Response(b"x" * (review._DISCOVERY_LIMIT + 1)),
        )
        for response in invalid:
            with self.subTest(status=response.status, headers=response.headers,
                              size=len(response.payload)):
                connection = _Connection(response)
                with patch.object(review.http.client, "HTTPSConnection",
                                  return_value=connection), self.assertRaises(ValueError):
                    review._read_fixed_public_https(review._DISCOVERY_PATH,
                                                     review._DISCOVERY_LIMIT)
                self.assertTrue(connection.closed)

    def test_existing_ingress_and_authentication_remain_disconnected(self):
        directory = Path(__file__).resolve().parent
        for filename in (
            "asgi_review_only_ingress.py",
            "server_oidc_preflight_review.py",
            "github_oidc_public_keys_transport_review.py",
            "github_runner_oidc_handoff_review.py",
            "composed_shadow_worker_offline.py",
        ):
            with self.subTest(filename=filename):
                self.assertNotIn("github_oidc_fixed_origin_transport_candidate",
                                 (directory / filename).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
