"""Additional offline failure and cross-bot fencing tests; no exchange access."""
import unittest

from entry_lifecycle_staging import EntryLifecycle, Phase
from order_reconciliation_staging import OrderOutcome
from shared_entry_gate_staging import inspect_entry


class SharedFakeStore:
    def __init__(self):
        self.owner = {}
        self.calls = 0
        self.fail = False

    def reserve(self, coin, bot, token):
        self.calls += 1
        if self.fail:
            raise ConnectionError("simulated reservation database outage")
        if coin in self.owner:
            return False
        self.owner[coin] = (bot, token)
        return True

    def claim_intent(self, coin, bot, token):
        self.calls += 1
        return self.owner.get(coin) == (bot, token)


def check(store, bot, action="open_long", *, flat=True, clear=True):
    return inspect_entry(
        store, bot=bot, trade={"hl_coin": "BTC", "action": action},
        exchange_position_flat=flat, exchange_orders_clear=clear,
    )


class FailureAndConflictTests(unittest.TestCase):
    def test_first_bot_fences_second_bot(self):
        store = SharedFakeStore()
        self.assertTrue(check(store, "aggressive").simulated_allowed)
        self.assertFalse(check(store, "intraday").simulated_allowed)
        self.assertFalse(check(store, "daily").simulated_allowed)

    def test_exchange_position_blocks_even_after_reservation(self):
        store = SharedFakeStore()
        result = check(store, "daily", flat=False)
        self.assertFalse(result.simulated_allowed)
        self.assertFalse(result.live_order_submitted)

    def test_pending_exchange_order_blocks_even_after_reservation(self):
        store = SharedFakeStore()
        self.assertFalse(check(store, "intraday", clear=False).simulated_allowed)

    def test_reservation_outage_never_submits_order(self):
        store = SharedFakeStore()
        store.fail = True
        with self.assertRaises(ConnectionError):
            check(store, "aggressive")
        # Error propagates from the offline adapter: live integration must
        # convert it to a fail-closed skipped entry, never a fallback order.
        self.assertEqual(store.calls, 1)

    def test_unknown_exchange_result_remains_fenced(self):
        lifecycle = EntryLifecycle()
        self.assertTrue(lifecycle.acquire(
            reserved=True, claimed=True, exchange_flat=True,
            no_open_orders=True,
        ))
        self.assertTrue(lifecycle.submit())
        lifecycle.observe(OrderOutcome.UNKNOWN)
        self.assertEqual(lifecycle.phase, Phase.UNCERTAIN)
        self.assertFalse(lifecycle.resolve_rejection(
            order_final=True, exchange_flat=True,
        ))

    def test_rejection_requires_final_and_flat_verification(self):
        lifecycle = EntryLifecycle()
        self.assertTrue(lifecycle.acquire(
            reserved=True, claimed=True, exchange_flat=True,
            no_open_orders=True,
        ))
        self.assertTrue(lifecycle.submit())
        lifecycle.observe(OrderOutcome.REJECTED)
        self.assertFalse(lifecycle.resolve_rejection(
            order_final=False, exchange_flat=True,
        ))
        self.assertFalse(lifecycle.resolve_rejection(
            order_final=True, exchange_flat=False,
        ))
        self.assertTrue(lifecycle.resolve_rejection(
            order_final=True, exchange_flat=True,
        ))


if __name__ == "__main__":
    unittest.main()
