"""No live SDK or network: durable SQLite-to-fake send tests only."""
import concurrent.futures
import os
import subprocess
import sys
import tempfile
import unittest

from offline_atomic_coordinator_fixture import OfflineAtomicCoordinator
from offline_atomic_fake_dispatch_ci import simulate_atomic_dispatch_once
from offline_shared_sender_prototype import FakeExchange

ACCOUNT = "0x" + "1" * 40
SCOPE = dict(environment="mainnet", account=ACCOUNT, dex="", coin="SOL")


class AtomicFakeDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "atomic.sqlite")
        self.coordinator = OfflineAtomicCoordinator(self.path, create=True)
        self.assertEqual(
            self.coordinator.reserve(
                principal="uid:daily", nonce="initial", bot="daily", **SCOPE,
            ),
            ("reserved_offline_only", False),
        )
        self.owner = self.coordinator.inspect(**SCOPE)
        self.assertEqual(self.owner[4], "reserved")
        self.fake = FakeExchange()

    def attempt(self, **overrides):
        args = dict(
            coordinator=self.coordinator, fake=self.fake, **SCOPE,
            token=self.owner[1], fence=self.owner[3],
        )
        args.update(overrides)
        return simulate_atomic_dispatch_once(**args)

    def test_marker_commits_before_fake_is_called(self):
        fake = self.fake
        original = fake.record_fake_attempt
        observed = []

        def inspect_at_fake(token, cloid):
            observed.append(OfflineAtomicCoordinator(self.path).inspect(**SCOPE))
            return original(token, cloid)

        fake.record_fake_attempt = inspect_at_fake
        result = self.attempt()
        self.assertEqual(result.state, "observed_unverified")
        self.assertFalse(result.submit_authorized)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][4], "dispatch_unknown")
        self.assertEqual(observed[0][2], self.owner[2])
        self.assertEqual(fake.attempts, [(self.owner[1], self.owner[2])])

    def test_restart_and_repeated_requests_never_fake_send_twice(self):
        self.assertEqual(self.attempt().state, "observed_unverified")
        self.coordinator = OfflineAtomicCoordinator(self.path)
        for _ in range(3):
            self.assertEqual(self.attempt().state, "hold")
        self.assertEqual(len(self.fake.attempts), 1)
        self.assertEqual(self.coordinator.inspect(**SCOPE)[4], "dispatch_unknown")
        self.assertEqual(
            self.coordinator.reserve(
                principal="uid:intraday", nonce="new",
                bot="intraday", **SCOPE,
            ),
            ("hold", False),
        )

    def test_lost_fake_ack_keeps_marker_and_blocks_restart(self):
        def accepted_but_response_lost(token, cloid):
            self.fake.attempts.append((token, cloid))
            raise TimeoutError("synthetic lost reply")

        self.fake.record_fake_attempt = accepted_but_response_lost
        self.assertEqual(self.attempt().state, "hold")
        self.coordinator = OfflineAtomicCoordinator(self.path)
        self.assertEqual(self.attempt().state, "hold")
        self.assertEqual(len(self.fake.attempts), 1)
        self.assertEqual(self.coordinator.inspect(**SCOPE)[4], "dispatch_unknown")

    def test_competing_restarted_senders_perform_at_most_one_fake_attempt(self):
        def contender(_):
            instance = OfflineAtomicCoordinator(self.path)
            return simulate_atomic_dispatch_once(
                coordinator=instance, fake=self.fake, **SCOPE,
                token=self.owner[1], fence=self.owner[3],
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(contender, range(12)))
        self.assertEqual(
            sum(r.state == "observed_unverified" for r in results), 1,
            results,
        )
        self.assertEqual(len(self.fake.attempts), 1)
        self.assertTrue(all(not r.submit_authorized for r in results))
        self.assertEqual(
            OfflineAtomicCoordinator(self.path).inspect(**SCOPE)[4],
            "dispatch_unknown",
        )

    def test_bad_claim_identity_or_type_never_marks_attempt(self):
        for change in (
            {"token": "stale"},
            {"fence": self.owner[3] + 1},
            {"account": "0x" + "2" * 40},
            {"environment": "testnet"},
            {"coin": "AVAX"},
            {"fake": object()},
            {"coordinator": object()},
        ):
            with self.subTest(change=change):
                decision = self.attempt(**change)
                self.assertEqual(decision.state, "hold")
                self.assertFalse(decision.submit_authorized)
        self.assertEqual(self.fake.attempts, [])
        self.assertEqual(self.coordinator.inspect(**SCOPE)[4], "reserved")

    def test_real_process_exits_after_marker_before_fake(self):
        script = """
import os,sys
from offline_atomic_coordinator_fixture import OfflineAtomicCoordinator
coordinator = OfflineAtomicCoordinator(sys.argv[1])
cloid = coordinator.mark_fake_dispatch_unknown(
    environment='mainnet', account=sys.argv[2], dex='', coin='SOL',
    token=sys.argv[3], fence=int(sys.argv[4]),
)
assert cloid == sys.argv[5], (cloid,sys.argv[5])
os._exit(41)
"""
        child = subprocess.run(
            [sys.executable, "-c", script, self.path, ACCOUNT,
             self.owner[1], str(self.owner[3]), self.owner[2]],
            timeout=12, check=False, capture_output=True, text=True,
        )
        self.assertEqual(child.returncode, 41, child.stderr)
        self.coordinator = OfflineAtomicCoordinator(self.path)
        self.assertEqual(self.attempt().state, "hold")
        self.assertEqual(self.fake.attempts, [])
        self.assertEqual(self.coordinator.inspect(**SCOPE)[4], "dispatch_unknown")

    def test_corrupt_or_missing_database_cannot_dispatch(self):
        os.unlink(self.path)
        self.assertEqual(self.attempt().state, "hold")
        self.assertEqual(self.fake.attempts, [])
        self.assertFalse(os.path.exists(self.path))


if __name__ == "__main__":
    unittest.main()
