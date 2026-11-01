"""Offline-only contract tests for shared entry admission.

No live credentials, orders, database, or network. The fake backend models
atomic storage, but cannot prove the real production backend is atomic.
"""
import threading
import unittest
import uuid
from shared_entry_admission import claim_shared_entry


class FakeAtomicCoordinator:
    def __init__(self):
        self.mutex = threading.Lock()
        self.claims = {}
        self.count = 0

    def claim_intent(self, *, bot, coin, action, request_id):
        with self.mutex:
            if coin in self.claims:
                return {"status": "blocked"}
            self.count += 1
            reply = {"status": "claimed", "bot": bot, "coin": coin,
                     "action": action, "request_id": request_id,
                     "intent_id": str(uuid.uuid4()), "fence_token": self.count}
            self.claims[coin] = reply
            return reply


class SharedEntryAdmissionTests(unittest.TestCase):
    def test_fails_closed_for_unavailable_backend(self):
        decision = claim_shared_entry(None, bot="daily", coin="SOL",
                                      action="open_long", request_id=str(uuid.uuid4()))
        self.assertFalse(decision.accepted)

    def test_three_bots_race_only_one_fake_claim(self):
        backend = FakeAtomicCoordinator()
        gate = threading.Barrier(3)
        outcomes = []
        lock = threading.Lock()

        def worker(bot):
            gate.wait()
            outcome = claim_shared_entry(backend, bot=bot, coin="SOL",
                                         action="open_long", request_id=str(uuid.uuid4()))
            with lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=worker, args=(bot,))
                   for bot in ("daily", "intraday", "aggressive")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)
            self.assertFalse(t.is_alive())
        self.assertEqual(sum(x.accepted for x in outcomes), 1)
        self.assertEqual(len(backend.claims), 1)

    def test_pyramid_competes_with_other_bot_open(self):
        backend = FakeAtomicCoordinator()
        a = claim_shared_entry(backend, bot="aggressive", coin="BTC",
                               action="pyramid_long", request_id=str(uuid.uuid4()))
        b = claim_shared_entry(backend, bot="daily", coin="BTC",
                               action="open_short", request_id=str(uuid.uuid4()))
        self.assertTrue(a.accepted)
        self.assertFalse(b.accepted)

    def test_bad_or_mismatched_evidence_is_rejected(self):
        request_id = str(uuid.uuid4())
        good = FakeAtomicCoordinator().claim_intent(
            bot="daily", coin="SOL", action="open_long", request_id=request_id)
        for changed in ({"bot": "intraday"}, {"coin": "BTC"},
                        {"request_id": str(uuid.uuid4())},
                        {"fence_token": "1"}, {"fence_token": 0},
                        {"intent_id": "unknown"}, {"status": "blocked"}):
            with self.subTest(changed=changed):
                proof = dict(good, **changed)
                class Fake:
                    def claim_intent(self, **kwargs):
                        return proof
                self.assertFalse(claim_shared_entry(
                    Fake(), bot="daily", coin="SOL",
                    action="open_long", request_id=request_id).accepted)

    def test_timeout_is_not_treated_as_approval(self):
        class Uncertain:
            def claim_intent(self, **kwargs):
                raise TimeoutError("after commit unknown")
        self.assertFalse(claim_shared_entry(
            Uncertain(), bot="aggressive", coin="SOL",
            action="pyramid_short", request_id=str(uuid.uuid4())).accepted)

    def test_fake_restart_retains_claim(self):
        backend = FakeAtomicCoordinator()
        first = claim_shared_entry(backend, bot="intraday", coin="LINK",
                                   action="open_long", request_id=str(uuid.uuid4()))
        later = claim_shared_entry(backend, bot="daily", coin="LINK",
                                   action="open_short", request_id=str(uuid.uuid4()))
        self.assertTrue(first.accepted)
        self.assertFalse(later.accepted)
        self.assertEqual(len(backend.claims), 1)


if __name__ == "__main__":
    unittest.main()
