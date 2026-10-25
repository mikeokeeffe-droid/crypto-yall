import unittest
from hyperliquid_reconciliation_pipeline_staging import evaluate_handoff, evaluate_release

ADDRESS = "0x" + "a" * 40

class Info:
    def __init__(self, active=False, open_order=False, fail=False):
        self.active, self.open_order, self.fail = active, open_order, fail
    def user_state(self, address):
        if self.fail:
            raise ConnectionError("unavailable")
        return {"assetPositions": [{"position": {"coin": "SOL", "szi": "1"}}] if self.active else []}
    def open_orders(self, address):
        return [{"coin": "SOL"}] if self.open_order else []
    def user_fills(self, address):
        return [{"coin": "SOL", "oid": 17, "sz": "1"}]
    def user_fills_by_time(self, address, start, end):
        return [{"coin": "SOL", "oid": 17, "sz": "1", "time": start, "tid": 99}]

class PipelineTests(unittest.TestCase):
    def test_verified_handoff(self):
        self.assertTrue(evaluate_handoff(Info(active=True), ADDRESS,
                        coin="SOL", order_id="17", clock=lambda: 100, order_start_ms=99000).allowed)
    def test_flat_handoff_rejected(self):
        self.assertFalse(evaluate_handoff(Info(), ADDRESS,
                         coin="SOL", order_id="17", clock=lambda: 100).allowed)
    def test_flat_release(self):
        self.assertTrue(evaluate_release(Info(), ADDRESS, coin="SOL",
                        clock=lambda: 100).allowed)
    def test_active_release_rejected(self):
        self.assertFalse(evaluate_release(Info(active=True), ADDRESS, coin="SOL",
                         clock=lambda: 100).allowed)
    def test_open_order_release_rejected(self):
        self.assertFalse(evaluate_release(Info(open_order=True), ADDRESS, coin="SOL",
                         clock=lambda: 100).allowed)
    def test_network_failure_closed(self):
        self.assertFalse(evaluate_release(Info(fail=True), ADDRESS, coin="SOL",
                         clock=lambda: 100).allowed)
    def test_stale_snapshot_rejected(self):
        ticks = iter([100, 120])
        self.assertFalse(evaluate_release(Info(), ADDRESS, coin="SOL",
                         clock=lambda: next(ticks)).allowed)

if __name__ == "__main__":
    unittest.main()
