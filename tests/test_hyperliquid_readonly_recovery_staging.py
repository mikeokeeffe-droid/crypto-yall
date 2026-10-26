"""Offline end-to-end evidence orchestration tests with fake Info client."""
import unittest
from entry_recovery_decision_staging import Decision
from hyperliquid_readonly_recovery_staging import reconcile_order_and_position

class Info:
    def __init__(self, status="rejected", fills=None, size="0", fail=None):
        self.status, self.fills, self.size, self.fail = status, fills if fills is not None else [], size, fail
    def order_status(self, address, oid):
        if self.fail == "order": raise ConnectionError()
        return {"order":{"status":self.status,"order":{"coin":"BTC","oid":oid}}}
    def user_fills(self, address):
        if self.fail == "fills": raise ConnectionError()
        return self.fills
    def user_state(self, address):
        if self.fail == "position": raise ConnectionError()
        return {"assetPositions":[{"position":{"coin":"BTC","szi":self.size}}]}

def decide(info):
    return reconcile_order_and_position(info, "fake", coin="BTC", order_id=42, requested_size=10)

class ReadonlyRecoveryTests(unittest.TestCase):
    def test_final_zero_fill_flat_releases(self):
        self.assertEqual(decide(Info()), Decision.RELEASE_NO_FILL)

    def test_partial_fill_owns_exposure(self):
        self.assertEqual(decide(Info(status="canceled",
            fills=[{"coin":"BTC","oid":42,"sz":"3"}], size="3")), Decision.OWN_POSITION)

    def test_open_order_keeps_fence(self):
        self.assertEqual(decide(Info(status="open")), Decision.KEEP_FENCED)

    def test_missing_any_exchange_evidence_keeps_fence(self):
        for step in ("order", "fills", "position"):
            with self.subTest(step=step):
                self.assertEqual(decide(Info(fail=step)), Decision.KEEP_FENCED)

if __name__ == "__main__":
    unittest.main()
