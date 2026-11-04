"""End-to-end synthetic entry competition and uncertain recovery tests."""
import threading
import unittest
import uuid
from offline_three_bot_simulation import (
    FakeSharedCoordinator, FakeExchange, simulate_entry)

class ThreeBotSimulationTests(unittest.TestCase):
    def test_simultaneous_opposing_entries_only_one_fake_submission(self):
        coordinator, exchange = FakeSharedCoordinator(), FakeExchange()
        gate = threading.Barrier(3)
        results = []
        mutex = threading.Lock()

        def worker(bot, action):
            gate.wait()
            result = simulate_entry(
                coordinator, exchange, bot=bot, coin="SOL", action=action,
                request_id=str(uuid.uuid4()))
            with mutex:
                results.append(result)

        workers = [
            threading.Thread(target=worker, args=pair)
            for pair in (("daily", "open_long"), ("intraday", "open_short"),
                         ("aggressive", "pyramid_long"))
        ]
        for worker_thread in workers:
            worker_thread.start()
        for worker_thread in workers:
            worker_thread.join(timeout=3)
            self.assertFalse(worker_thread.is_alive())
        self.assertEqual(len(results), 3)
        self.assertEqual(sum(x.accepted for x in results), 1)
        self.assertEqual(len(exchange.submissions), 1)
        self.assertEqual(len(coordinator.claims), 1)
        self.assertEqual(exchange.submissions[0][3],
                         coordinator.claims["SOL"]["intent_id"])

    def test_uncertain_commit_blocks_every_fake_submission_after_restart(self):
        coordinator, exchange = FakeSharedCoordinator(), FakeExchange()
        coordinator.lose_confirmation_for.add("ETH")
        first = simulate_entry(
            coordinator, exchange, bot="daily", coin="ETH",
            action="open_long", request_id=str(uuid.uuid4()))
        self.assertFalse(first.accepted)
        self.assertEqual(first.reason, "coordinator_result_uncertain")
        self.assertEqual(len(coordinator.claims), 1)
        for bot, action in (("daily", "open_long"),
                            ("intraday", "open_short"),
                            ("aggressive", "pyramid_long")):
            later = simulate_entry(
                coordinator, exchange, bot=bot, coin="ETH", action=action,
                request_id=str(uuid.uuid4()))
            self.assertFalse(later.accepted)
        self.assertEqual(exchange.submissions, [])

    def test_separate_coins_have_separate_fake_reservations(self):
        coordinator, exchange = FakeSharedCoordinator(), FakeExchange()
        for bot, coin in (("daily", "SOL"), ("intraday", "ETH"),
                          ("aggressive", "BTC")):
            decision = simulate_entry(
                coordinator, exchange, bot=bot, coin=coin,
                action="open_long", request_id=str(uuid.uuid4()))
            self.assertTrue(decision.accepted)
        self.assertEqual(len(exchange.submissions), 3)
        self.assertEqual(set(coordinator.claims), {"SOL", "ETH", "BTC"})

    def test_fake_exchange_timeout_keeps_reservation_and_blocks_other_bots(self):
        class LostFakeOrderResponse(FakeExchange):
            def submit_fake(self, **kwargs):
                super().submit_fake(**kwargs)
                raise TimeoutError("synthetic exchange accepted then response lost")

        coordinator, exchange = FakeSharedCoordinator(), LostFakeOrderResponse()
        with self.assertRaises(TimeoutError):
            simulate_entry(
                coordinator, exchange, bot="daily", coin="LINK",
                action="open_long", request_id=str(uuid.uuid4()))
        self.assertEqual(len(exchange.submissions), 1)
        original = dict(coordinator.claims["LINK"])
        for bot, action in (("intraday", "open_short"),
                            ("aggressive", "pyramid_long")):
            result = simulate_entry(
                coordinator, exchange, bot=bot, coin="LINK",
                action=action, request_id=str(uuid.uuid4()))
            self.assertFalse(result.accepted)
        self.assertEqual(len(exchange.submissions), 1)
        self.assertEqual(coordinator.claims["LINK"], original)

    def test_fake_exchange_rejection_never_automatically_releases_claim(self):
        class RejectingFakeExchange(FakeExchange):
            def submit_fake(self, **kwargs):
                raise ValueError("synthetic order rejected")

        coordinator, exchange = FakeSharedCoordinator(), RejectingFakeExchange()
        with self.assertRaises(ValueError):
            simulate_entry(
                coordinator, exchange, bot="aggressive", coin="AVAX",
                action="open_short", request_id=str(uuid.uuid4()))
        self.assertIn("AVAX", coordinator.claims)
        second = simulate_entry(
            coordinator, exchange, bot="intraday", coin="AVAX",
            action="open_long", request_id=str(uuid.uuid4()))
        self.assertFalse(second.accepted)
        self.assertEqual(exchange.submissions, [])

if __name__ == "__main__":
    unittest.main()
