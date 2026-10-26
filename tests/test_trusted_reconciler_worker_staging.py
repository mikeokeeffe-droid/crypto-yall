import unittest
from trusted_reconciler_worker_staging import reconcile_entry, reconcile_closed

ADDRESS = "0x" + "a" * 40
class Info:
    def __init__(self, active=True, fail=False):
        self.active, self.fail = active, fail
    def user_state(self, address):
        if self.fail: raise ConnectionError("unavailable")
        return {"assetPositions": [{"position": {"coin": "SOL", "szi": "1"}}] if self.active else []}
    def open_orders(self, address): return []
    def user_fills(self, address): return []
    def user_fills_by_time(self, address, start, end):
        return [{"coin": "SOL", "oid": 17, "sz": "1", "time": start, "tid": 99}]

class WorkerTests(unittest.TestCase):
    def test_valid_entry_is_only_candidate(self):
        result = reconcile_entry(Info(), ADDRESS, coin="SOL", order_id=17,
                                 order_start_ms=99000, clock=lambda: 100)
        self.assertEqual(result.action, "handoff_candidate")
    def test_missing_order_identity_holds(self):
        self.assertEqual(reconcile_entry(Info(), ADDRESS, coin="SOL", order_id=None,
                         order_start_ms=99000, clock=lambda: 100).action, "hold")
    def test_missing_submission_timestamp_holds(self):
        self.assertEqual(reconcile_entry(Info(), ADDRESS, coin="SOL", order_id=17,
                         order_start_ms=None, clock=lambda: 100).action, "hold")
    def test_malformed_order_identity_and_timestamp_hold_without_exchange_reads(self):
        class NoReads:
            def __getattr__(self, name):
                raise AssertionError("invalid input must not read exchange")
        for order_id, start in ((True, 99000), (-1, 99000), (17, True), (17, -1)):
            with self.subTest(order_id=order_id, start=start):
                result = reconcile_entry(NoReads(), ADDRESS, coin="SOL",
                                         order_id=order_id,
                                         order_start_ms=start, clock=lambda: 100)
                self.assertEqual(result.action, "hold")

    def test_flat_entry_holds(self):
        self.assertEqual(reconcile_entry(Info(active=False), ADDRESS, coin="SOL", order_id=17,
                         order_start_ms=99000, clock=lambda: 100).action, "hold")
    def test_flat_release_is_only_candidate(self):
        self.assertEqual(reconcile_closed(Info(active=False), ADDRESS, coin="SOL",
                         clock=lambda: 100).action, "release_candidate")
    def test_network_failure_holds(self):
        self.assertEqual(reconcile_closed(Info(fail=True), ADDRESS, coin="SOL",
                         clock=lambda: 100).action, "hold")

if __name__ == "__main__":
    unittest.main()
