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


    def test_malformed_coordinator_replies_never_grant_entry(self):
        request_id = str(uuid.uuid4())
        good = FakeAtomicCoordinator().claim_intent(
            bot="daily", coin="SOL", action="open_long", request_id=request_id)
        invalid = (
            None, [], "claimed", True, 1,
            dict(good, fence_token=True),
            dict(good, fence_token=1.0),
            dict(good, intent_id=None),
            dict(good, intent_id=True),
            dict(good, intent_id=str(uuid.uuid4()).upper()),
            dict(good, action="open_short"),
            dict(good, status=True),
        )
        for proof in invalid:
            with self.subTest(proof=repr(proof)):
                class Fake:
                    def claim_intent(self, **kwargs):
                        return proof
                decision = claim_shared_entry(
                    Fake(), bot="daily", coin="SOL",
                    action="open_long", request_id=request_id)
                self.assertIs(decision.accepted, False)
                self.assertEqual(decision.intent_id, "")
                self.assertEqual(decision.fence_token, 0)

    def test_timeout_after_fake_commit_never_approves_or_retries(self):
        class CommitThenTimeout:
            def __init__(self):
                self.calls = 0
                self.persisted = False
            def claim_intent(self, **kwargs):
                self.calls += 1
                self.persisted = True
                raise TimeoutError("response lost after durable write")
        backend = CommitThenTimeout()
        result = claim_shared_entry(
            backend, bot="intraday", coin="ETH",
            action="open_short", request_id=str(uuid.uuid4()))
        self.assertTrue(backend.persisted)
        self.assertEqual(backend.calls, 1)
        self.assertIs(result.accepted, False)
        self.assertEqual(result.reason, "coordinator_result_uncertain")

    def test_invalid_input_types_do_not_call_coordinator(self):
        class Spy:
            calls = 0
            def claim_intent(self, **kwargs):
                self.calls += 1
                raise AssertionError("invalid inputs must not reach backend")
        valid = dict(bot="daily", coin="SOL", action="open_long",
                     request_id=str(uuid.uuid4()))
        for key, values in (
            ("bot", (None, [], {}, True)),
            ("action", (None, [], {}, True)),
            ("coin", (None, [], {}, True, "sol", "")),
            ("request_id", (None, [], {}, True, "invalid")),
        ):
            for value in values:
                with self.subTest(key=key, value=repr(value)):
                    backend = Spy()
                    decision = claim_shared_entry(
                        backend, **dict(valid, **{key: value}))
                    self.assertIs(decision.accepted, False)
                    self.assertEqual(backend.calls, 0)

    def test_three_bots_opposing_actions_one_shared_coin(self):
        backend = FakeAtomicCoordinator()
        gate = threading.Barrier(3)
        outcomes = []
        lock = threading.Lock()
        scenarios = (
            ("daily", "open_long"),
            ("intraday", "open_short"),
            ("aggressive", "pyramid_long"),
        )

        def worker(bot, action):
            gate.wait()
            decision = claim_shared_entry(
                backend, bot=bot, coin="SOL", action=action,
                request_id=str(uuid.uuid4()))
            with lock:
                outcomes.append((bot, decision))

        threads = [threading.Thread(target=worker, args=item)
                   for item in scenarios]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcomes), 3)
        self.assertEqual(sum(decision.accepted for _, decision in outcomes), 1)
        self.assertEqual(len(backend.claims), 1)
        self.assertEqual(set(backend.claims), {"SOL"})

    def test_separate_coins_do_not_share_fake_reservation(self):
        backend = FakeAtomicCoordinator()
        outcomes = [
            claim_shared_entry(
                backend, bot=bot, coin=coin, action="open_long",
                request_id=str(uuid.uuid4()))
            for bot, coin in (
                ("daily", "SOL"), ("intraday", "ETH"), ("aggressive", "BTC"))
        ]
        self.assertTrue(all(decision.accepted for decision in outcomes))
        self.assertEqual(set(backend.claims), {"SOL", "ETH", "BTC"})

    def test_lost_confirmation_keeps_other_bots_blocked(self):
        class LostFirstConfirmation(FakeAtomicCoordinator):
            def __init__(self):
                super().__init__()
                self.lost = False

            def claim_intent(self, **kwargs):
                reply = super().claim_intent(**kwargs)
                if reply.get("status") == "claimed" and not self.lost:
                    self.lost = True
                    raise TimeoutError("claim committed but response lost")
                return reply

        backend = LostFirstConfirmation()
        first = claim_shared_entry(
            backend, bot="daily", coin="SOL", action="open_long",
            request_id=str(uuid.uuid4()))
        self.assertFalse(first.accepted)
        self.assertEqual(first.reason, "coordinator_result_uncertain")
        self.assertIn("SOL", backend.claims)

        for bot, action in (
            ("intraday", "open_short"),
            ("aggressive", "pyramid_long"),
        ):
            with self.subTest(bot=bot):
                later = claim_shared_entry(
                    backend, bot=bot, coin="SOL", action=action,
                    request_id=str(uuid.uuid4()))
                self.assertFalse(later.accepted)
        self.assertEqual(len(backend.claims), 1)

    def test_failed_backend_never_falls_back_to_local_approval(self):
        class Unavailable:
            def claim_intent(self, **kwargs):
                raise ConnectionError("shared coordinator unavailable")

        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                decision = claim_shared_entry(
                    Unavailable(), bot=bot, coin="BTC",
                    action="open_long", request_id=str(uuid.uuid4()))
                self.assertFalse(decision.accepted)
                self.assertEqual(decision.fence_token, 0)

if __name__ == "__main__":
    unittest.main()
