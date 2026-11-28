"""Offline-only capture digest and scope tests; no HTTP or database."""
import hashlib
import json
import unittest
import uuid

from offline_ci_info_capture_integrity import review_synthetic_info_capture

ACCOUNT="0x"+"1"*40
CLOID="0x"+"a"*32
TOKEN=uuid.UUID("12345678-1234-4234-8234-123456789abc")
ENDPOINT="https://api.hyperliquid.xyz/info"
NOW=150000
ORDER=b'{"status":"synthetic"}'
FILLS=b'[{"tid":123}]'


class SyntheticCaptureIntegrityTests(unittest.TestCase):
    def make(self, body=ORDER, kind="orderStatus", **changes):
        manifest={
            "origin":"fixture",
            "environment":"mainnet",
            "endpoint":ENDPOINT,
            "method":"POST",
            "account":ACCOUNT,
            "dex":"",
            "request_type":kind,
            "token":str(TOKEN),
            "fence":4,
            "cloid":CLOID,
            "response_sha256":hashlib.sha256(body).hexdigest(),
            "response_bytes":len(body),
            "captured_at_ms":NOW-100,
            "status_code":200,
            "redirect_count":0,
            "transport_verified":False,
        }
        manifest.update(changes)
        return manifest

    def review(self, manifest, body=ORDER, kind="orderStatus", **changes):
        args={
            "manifest":manifest,
            "raw_response":body,
            "expected_environment":"mainnet",
            "expected_account":ACCOUNT,
            "expected_token":TOKEN,
            "expected_fence":4,
            "expected_cloid":CLOID,
            "expected_request_type":kind,
            "now_ms":NOW,
        }
        args.update(changes)
        return review_synthetic_info_capture(**args)

    def test_matching_order_and_fill_fixtures_only_review(self):
        for kind,body in (("orderStatus",ORDER),
                          ("userFillsByTime",FILLS)):
            with self.subTest(kind=kind):
                result=self.review(self.make(body,kind),body,kind)
                self.assertEqual(result.state,"review_only")
                self.assertEqual(result.response_sha256,
                                 hashlib.sha256(body).hexdigest())
                self.assertFalse(result.origin_authenticated)
                self.assertFalse(result.ownership_verified)
                self.assertFalse(result.submit_authorized)

    def test_tampered_response_never_passes_digest_check(self):
        body=b'{"status":"different"}'
        result=self.review(self.make(),body)
        self.assertEqual(result.state,"hold")
        self.assertIn("changed",result.reason)

    def test_wrong_order_scope_principal_or_provenance_holds(self):
        changes=[
            {"account":"0x"+"2"*40},
            {"environment":"testnet"},
            {"endpoint":"https://api.hyperliquid-testnet.xyz/info"},
            {"method":"GET"},
            {"request_type":"order"},
            {"token":str(uuid.uuid4())},
            {"fence":5},
            {"cloid":"0x"+"b"*32},
            {"origin":"exchange"},
            {"origin":"authenticated"},
            {"transport_verified":True},
            {"status_code":429},
            {"redirect_count":1},
            {"dex":"some-other-dex"},
            {"authenticated":True},
        ]
        for change in changes:
            with self.subTest(change=change):
                self.assertEqual(self.review(self.make(**change)).state,"hold")

    def test_partial_stale_future_and_malformed_json_holds(self):
        for stamp in (-1, NOW+1, NOW-60001, True):
            with self.subTest(stamp=stamp):
                self.assertEqual(self.review(
                    self.make(captured_at_ms=stamp)).state,"hold")
        for body in (b'',b'{',b'{"a":1,"a":2}',
                     b'{"size":NaN}', b'[]', b'x'*262145):
            with self.subTest(body=body[:25]):
                self.assertEqual(self.review(self.make(body),body).state,"hold")
        self.assertEqual(self.review(self.make(response_bytes=1)).state,"hold")
        self.assertEqual(self.review(
            self.make(response_sha256="0"*64)).state,"hold")

    def test_pinned_intent_mismatch_holds(self):
        for change in (
            {"expected_account":"0x"+"2"*40},
            {"expected_environment":"testnet"},
            {"expected_token":uuid.uuid4()},
            {"expected_fence":5},
            {"expected_cloid":"0x"+"b"*32},
            {"expected_request_type":"userFillsByTime"},
            {"now_ms":NOW+60001},
        ):
            with self.subTest(change=change):
                self.assertEqual(self.review(self.make(),**change).state,"hold")

    def test_module_has_no_transport_or_trading_methods(self):
        import offline_ci_info_capture_integrity as module
        self.assertFalse(hasattr(module,"send_order"))
        self.assertFalse(hasattr(module,"market_open"))
        self.assertFalse(hasattr(module,"request"))


if __name__=="__main__":
    unittest.main()
