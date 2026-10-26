import unittest
from executor_entry_dry_run_staging import simulate_executor_entry


class FakeStore:
    def __init__(self, reserve=True, claim=True):
        self.reserve_ok = reserve
        self.claim_ok = claim
    def reserve(self, coin, bot, token):
        return self.reserve_ok
    def claim_intent(self, coin, bot, token):
        return self.claim_ok


class DryRunTests(unittest.TestCase):
    def test_simulated_allowed_never_sends_order(self):
        sent = []
        result = simulate_executor_entry(
            FakeStore(), coin="BTC", bot="aggressive",
            exchange_position_flat=True, exchange_orders_clear=True,
            order_sender=lambda *args: sent.append(args),
        )
        self.assertTrue(result.simulated_allowed)
        self.assertFalse(result.live_order_submitted)
        self.assertEqual(sent, [])

    def test_reservation_denial_never_sends_order(self):
        sent = []
        result = simulate_executor_entry(
            FakeStore(reserve=False), coin="ETH", bot="intraday",
            exchange_position_flat=True, exchange_orders_clear=True,
            order_sender=lambda *args: sent.append(args),
        )
        self.assertFalse(result.simulated_allowed)
        self.assertEqual(sent, [])

    def test_existing_position_denies(self):
        result = simulate_executor_entry(
            FakeStore(), coin="SOL", bot="daily",
            exchange_position_flat=False, exchange_orders_clear=True,
        )
        self.assertFalse(result.simulated_allowed)

    def test_unsafe_evidence_never_touches_reservation_store(self):
        class NeverReserve:
            def reserve(self, *args):
                raise AssertionError("unsafe evidence must not reserve")
            def claim_intent(self, *args):
                raise AssertionError("unsafe evidence must not claim")
        for flat, clear in ((False, True), (True, False), (None, True), (True, 1)):
            with self.subTest(flat=flat, clear=clear):
                result = simulate_executor_entry(
                    NeverReserve(), coin="SOL", bot="intraday",
                    exchange_position_flat=flat, exchange_orders_clear=clear)
                self.assertFalse(result.simulated_allowed)

    def test_pending_order_denies(self):
        result = simulate_executor_entry(
            FakeStore(), coin="SUI", bot="aggressive",
            exchange_position_flat=True, exchange_orders_clear=False,
        )
        self.assertFalse(result.simulated_allowed)


if __name__ == "__main__":
    unittest.main()
