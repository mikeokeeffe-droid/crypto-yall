"""Offline integration contract tests; no network, no exchange, no database."""
import unittest
from entry_gate_staging import acquire_entry_permit


class FakeStore:
    def __init__(self, reserve=True, claim=True, fail=None):
        self.reserve_ok = reserve
        self.claim_ok = claim
        self.fail = fail
        self.calls = []

    def reserve(self, coin, bot, token):
        self.calls.append(("reserve", coin, bot, token))
        if self.fail == "reserve":
            raise TimeoutError("reservation unavailable")
        return self.reserve_ok

    def claim_intent(self, coin, bot, token):
        self.calls.append(("claim", coin, bot, token))
        if self.fail == "claim":
            raise TimeoutError("claim status unknown")
        return self.claim_ok


class GateTests(unittest.TestCase):
    def test_both_steps_required(self):
        store = FakeStore()
        permit = acquire_entry_permit(store, "BTC", "aggressive")
        self.assertIsNotNone(permit)
        self.assertEqual(len(store.calls), 2)
        self.assertEqual(store.calls[0][3], store.calls[1][3])

    def test_competing_reservation_blocks(self):
        store = FakeStore(reserve=False)
        self.assertIsNone(acquire_entry_permit(store, "BTC", "intraday"))
        self.assertEqual(len(store.calls), 1)

    def test_claim_rejected_blocks(self):
        self.assertIsNone(
            acquire_entry_permit(FakeStore(claim=False), "BTC", "daily")
        )

    def test_reservation_timeout_fails_closed(self):
        self.assertIsNone(
            acquire_entry_permit(FakeStore(fail="reserve"), "BTC", "aggressive")
        )

    def test_ambiguous_claim_timeout_fails_closed(self):
        self.assertIsNone(
            acquire_entry_permit(FakeStore(fail="claim"), "BTC", "intraday")
        )


if __name__ == "__main__":
    unittest.main()
