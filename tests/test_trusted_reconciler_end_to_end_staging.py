"""Offline end-to-end tests: real evidence code, mocked exchange and RPC."""
import unittest
from trusted_reconciler_service_staging import reconcile_submitted_entry, reconcile_flat_owner

ADDR = "0x" + "a" * 40

class Exchange:
    def __init__(self):
        self.active = True
        self.orders = []
        self.fills = [{"coin": "SOL", "oid": 17, "sz": "1", "time": 99000, "tid": 12}]
        self.calls = 0
    def user_state(self, address):
        self.calls += 1
        return {"assetPositions": [{"position": {"coin": "SOL", "szi": "1"}}] if self.active else []}
    def open_orders(self, address): return self.orders
    def user_fills(self, address): return self.fills
    def user_fills_by_time(self, address, start, end): return self.fills

class IntegrationTests(unittest.TestCase):
    def test_entry_then_flat_release(self):
        exchange = Exchange()
        calls = []
        def rpc(name, params):
            calls.append(name)
            return True
        entry = reconcile_submitted_entry(exchange, ADDR, rpc, coin="SOL",
                     bot="intraday", token="durable-token", order_id=17,
                     order_start_ms=99000, clock=lambda: 100)
        self.assertTrue(entry.confirmed, entry.reason)
        exchange.active = False
        released = reconcile_flat_owner(exchange, ADDR, rpc, coin="SOL",
                     bot="intraday", token="durable-token", clock=lambda: 100)
        self.assertTrue(released.confirmed, released.reason)
        self.assertEqual(calls, ["record_bot_position_owner",
                                "mark_bot_position_closed",
                                "release_closed_bot_position"])
        self.assertGreaterEqual(exchange.calls, 3)

    def test_incomplete_evidence_never_calls_rpc(self):
        exchange = Exchange()
        exchange.fills = []
        calls = []
        result = reconcile_submitted_entry(exchange, ADDR,
                   lambda *args: calls.append(args) or True,
                   coin="SOL", bot="intraday", token="durable-token",
                   order_id=17, order_start_ms=99000, clock=lambda: 100)
        self.assertFalse(result.confirmed)
        self.assertEqual(calls, [])

if __name__ == "__main__":
    unittest.main()
