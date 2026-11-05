"""Fake-only claim release checks: no production services."""
import unittest
from types import SimpleNamespace
from offline_hyperliquid_claim_release_gate import inspect_synthetic_claim_release_offline

class ClaimReleaseGateTests(unittest.TestCase):
    def check(self, legacy, strict="parsed_untrusted",
              ownership="review_only", restart="review_only"):
        return inspect_synthetic_claim_release_offline(
            legacy_result=legacy,
            strict_fill_review=SimpleNamespace(status=strict),
            ownership_review=SimpleNamespace(status=ownership),
            restart_review=SimpleNamespace(status=restart))

    def test_filled_receipt_and_all_positive_claims_still_hold(self):
        result = self.check({"status": "filled", "oid": 42, "fill_size": 1})
        self.assertEqual(result.status, "hold")
        self.assertIs(result.release_claim, False)
        self.assertIs(result.allow_new_entry, False)

    def test_unfilled_and_malformed_receipts_hold(self):
        for raw in (None, [], {}, {"status": "unknown"},
                    {"status": "error"}, {"status": "approved"},
                    {"status": "filled", "fill_size": -1}):
            with self.subTest(raw=repr(raw)):
                result = self.check(raw)
                self.assertEqual(result.status, "hold")
                self.assertFalse(result.release_claim)

    def test_any_unresolved_or_forged_review_holds(self):
        for field in ("strict", "ownership", "restart"):
            for value in ("hold", "approved", True, None, ["review_only"]):
                with self.subTest(field=field, value=repr(value)):
                    args = {field: value}
                    result = self.check({"status": "filled"}, **args)
                    self.assertEqual(result.status, "hold")
                    self.assertFalse(result.allow_new_entry)

    def test_throwing_review_attribute_holds(self):
        class Hostile:
            @property
            def status(self):
                raise RuntimeError("unavailable")
        result = inspect_synthetic_claim_release_offline(
            legacy_result={"status": "filled"},
            strict_fill_review=Hostile(),
            ownership_review=SimpleNamespace(status="review_only"),
            restart_review=SimpleNamespace(status="review_only"))
        self.assertEqual(result.status, "hold")
        self.assertFalse(result.release_claim)

if __name__ == "__main__":
    unittest.main()
