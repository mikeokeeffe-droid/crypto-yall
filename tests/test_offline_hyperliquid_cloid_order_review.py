"""Offline CLOID-to-OID checks, never exchange access or live execution."""
import copy
import unittest
import uuid

from offline_hyperliquid_cloid_order_review import review_cloid_order_lineage_offline

ACCOUNT = "0x" + "a" * 40
CLOID = "0x" + "b" * 32
TOKEN = str(uuid.UUID("12345678-1234-1234-1234-123456789abc"))

def fixture():
    intent = dict(
        bot="daily", environment="mainnet", account=ACCOUNT, dex="",
        coin="SOL", action="open_long", requested_size="2",
        intent_token=TOKEN, fence_token=42, cloid=CLOID,
        submitted_at_ms=100_000,
    )
    request = {"type": "orderStatus", "user": ACCOUNT, "oid": CLOID}
    response = {"status": "order", "order": {
        "status": "filled", "statusTimestamp": 101_000,
        "order": {"coin": "SOL", "side": "B", "oid": 1001,
                  "cloid": CLOID, "origSz": "2.0", "sz": "0.0",
                  "reduceOnly": False, "timestamp": 100_200}
    }}
    return dict(intent=intent, request=request, response=response,
                captured_at_ms=102_000)

def review(data):
    return review_cloid_order_lineage_offline(**data)

class CloidOrderLineageOfflineTests(unittest.TestCase):
    def test_exact_synthetic_match_still_holds(self):
        result = review(fixture())
        self.assertEqual(result.status, "hold")
        self.assertTrue(result.structurally_consistent)
        self.assertEqual(result.observed_oid, 1001)
        self.assertFalse(result.submit_authorized)

    def test_wrong_account_cloid_and_request_type_hold(self):
        for key, value in (("user","0x" + "c" * 40),
                           ("oid","0x" + "d" * 32),
                           ("type","openOrders")):
            with self.subTest(key=key):
                data = fixture()
                data["request"][key] = value
                self.assertFalse(review(data).structurally_consistent)

    def test_wrong_returned_cloid_oid_size_coin_side_hold(self):
        for field, value in (("cloid","0x" + "c" * 32), ("cloid",None),
                             ("oid",0), ("oid",True), ("coin","BTC"),
                             ("side","A"), ("origSz","3"),
                             ("reduceOnly",True), ("sz","1")):
            with self.subTest(field=field, value=value):
                data = fixture()
                data["response"]["order"]["order"][field] = value
                self.assertFalse(review(data).structurally_consistent)

    def test_incorrect_identity_and_malformed_cloid_hold(self):
        for field, value in (("bot","unknown"),("environment","other"),
                             ("account","0x123"),("dex","other"),
                             ("intent_token","not-uuid"),
                             ("fence_token",0),("fence_token",True),
                             ("cloid","0x" + "x" * 32),
                             ("cloid","0x" + "b" * 31),
                             ("requested_size","NaN"),
                             ("requested_size","-2")):
            with self.subTest(field=field):
                data = fixture()
                data["intent"][field] = value
                self.assertFalse(review(data).structurally_consistent)

    def test_unknown_rejected_partial_or_open_order_holds(self):
        for status in ("unknown", "rejected", "open", "canceled", "triggered"):
            with self.subTest(status=status):
                data = fixture()
                data["response"]["order"]["status"] = status
                self.assertFalse(review(data).structurally_consistent)
        data = fixture()
        data["response"]["status"] = "unknownOid"
        self.assertFalse(review(data).structurally_consistent)

    def test_order_and_capture_time_anomalies_hold(self):
        for when in (99_999, 103_000, True):
            with self.subTest(when=when):
                data = fixture()
                data["response"]["order"]["order"]["timestamp"] = when
                self.assertFalse(review(data).structurally_consistent)
        data = fixture()
        data["captured_at_ms"] = 100_000
        self.assertFalse(review(data).structurally_consistent)

    def test_synthetic_authentication_flag_never_grants_ownership(self):
        data = fixture()
        data["intent"]["authenticated"] = True
        self.assertFalse(review(data).structurally_consistent)
        data = fixture()
        data["response"]["authenticated"] = True
        result = review(data)
        self.assertEqual(result.status, "hold")
        self.assertFalse(result.submit_authorized)

    def test_no_exchange_or_order_dispatch_imports(self):
        import offline_hyperliquid_cloid_order_review as module
        for name in ("submit_order", "market_open", "market_close", "fetch_page"):
            self.assertFalse(hasattr(module, name))

if __name__ == "__main__":
    unittest.main()
