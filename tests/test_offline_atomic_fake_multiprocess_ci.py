"""Multiprocess fault-injection for the disposable SQLite/fake sender.

Only offline fixtures; no Hyperliquid SDK, trading key, network, or live bot.
These tests exercise independent OS processes, not production credential isolation.
"""
import multiprocessing
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from offline_atomic_coordinator_fixture import OfflineAtomicCoordinator
from offline_atomic_fake_dispatch_ci import simulate_atomic_dispatch_once
from offline_shared_sender_prototype import FakeExchange

ACCOUNT = "0x" + "1" * 40
SCOPE = dict(environment="mainnet", account=ACCOUNT, dex="", coin="SOL")


def _competing_fake_sender(path, token, fence, start, ready, results):
    """Separate process opens its own journal and owns a local fake recorder."""
    ready.put(True)
    if not start.wait(timeout=15):
        results.put(("not_started", 0, False))
        return
    try:
        journal = OfflineAtomicCoordinator(path)
        fake = FakeExchange()
        decision = simulate_atomic_dispatch_once(
            coordinator=journal, fake=fake, token=token, fence=fence, **SCOPE,
        )
        results.put((decision.state, len(fake.attempts),
                     decision.submit_authorized))
    except Exception as exc:
        results.put(("error:" + type(exc).__name__, 0, False))


class AtomicFakeMultiprocessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "claims.sqlite")
        journal = OfflineAtomicCoordinator(self.path, create=True)
        self.assertEqual(
            journal.reserve(
                principal="daily-worker", nonce="initial", bot="daily",
                **SCOPE,
            ),
            ("reserved_offline_only", False),
        )
        self.claim = journal.inspect(**SCOPE)
        self.assertEqual(self.claim[4], "reserved")

    def competing_processes(self, count=8):
        ctx = multiprocessing.get_context("fork")
        start = ctx.Event()
        ready = ctx.Queue()
        results = ctx.Queue()
        workers = [
            ctx.Process(
                target=_competing_fake_sender,
                args=(self.path, self.claim[1], self.claim[3],
                      start, ready, results),
            )
            for _ in range(count)
        ]
        try:
            for worker in workers:
                worker.start()
            for _ in workers:
                self.assertTrue(ready.get(timeout=12))
            start.set()
            decisions = [results.get(timeout=20) for _ in workers]
            for worker in workers:
                worker.join(timeout=10)
                self.assertEqual(worker.exitcode, 0)
            return decisions
        finally:
            start.set()
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                worker.join(timeout=5)
            ready.close()
            results.close()

    def test_eight_independent_senders_share_one_durable_fake_attempt(self):
        decisions = self.competing_processes()
        self.assertEqual(
            sum(state == "observed_unverified" for state, _, _ in decisions),
            1, decisions,
        )
        self.assertEqual(
            sum(state == "hold" for state, _, _ in decisions), 7,
            decisions,
        )
        self.assertEqual(sum(attempts for _, attempts, _ in decisions), 1)
        self.assertTrue(all(not authorised for _, _, authorised in decisions))
        journal = OfflineAtomicCoordinator(self.path)
        self.assertEqual(journal.inspect(**SCOPE)[4], "dispatch_unknown")
        self.assertEqual(journal.reserve(
            principal="intraday-worker", nonce="after-race",
            bot="intraday", **SCOPE,
        ), ("hold", False))

    def test_process_crash_after_fake_effect_before_ack_blocks_all_restarts(self):
        attempt_log = os.path.join(self.temp.name, "fake-effect.txt")
        script = """
import os,sys
from offline_atomic_coordinator_fixture import OfflineAtomicCoordinator
from offline_atomic_fake_dispatch_ci import simulate_atomic_dispatch_once
from offline_shared_sender_prototype import FakeExchange
journal=OfflineAtomicCoordinator(sys.argv[1])
fake=FakeExchange()
def fake_side_effect_then_die(token,cloid):
    with open(sys.argv[2],"w",encoding="utf-8") as event:
        event.write(token+" "+cloid)
        event.flush()
        os.fsync(event.fileno())
    os._exit(73)
fake.record_fake_attempt=fake_side_effect_then_die
simulate_atomic_dispatch_once(
    coordinator=journal, fake=fake, environment="mainnet",
    account=sys.argv[3], dex="", coin="SOL",
    token=sys.argv[4], fence=int(sys.argv[5]),
)
sys.exit(99)
"""
        child = subprocess.run(
            [sys.executable, "-c", script, self.path, attempt_log, ACCOUNT,
             self.claim[1], str(self.claim[3])],
            check=False, capture_output=True, text=True, timeout=12,
        )
        self.assertEqual(child.returncode, 73, child.stderr)
        with open(attempt_log, encoding="utf-8") as recorded:
            self.assertEqual(
                recorded.read(), self.claim[1] + " " + self.claim[2],
            )
        self.assertEqual(
            OfflineAtomicCoordinator(self.path).inspect(**SCOPE)[4],
            "dispatch_unknown",
        )
        decisions = self.competing_processes()
        self.assertEqual(decisions, [("hold", 0, False)] * len(decisions))
        with open(attempt_log, encoding="utf-8") as recorded:
            self.assertEqual(
                recorded.read(), self.claim[1] + " " + self.claim[2],
            )

    def test_abrupt_exit_before_marker_commit_allows_one_first_fake_send(self):
        script = """
import os,sqlite3,sys
from pathlib import Path
uri=Path(sys.argv[1]).absolute().as_uri()+"?mode=rw"
db=sqlite3.connect(uri,uri=True,isolation_level=None)
db.execute("BEGIN IMMEDIATE")
updated=db.execute(
    "UPDATE claims SET state='dispatch_unknown' "
    "WHERE token=? AND fence=? AND state='reserved'",
    (sys.argv[2],int(sys.argv[3])),
).rowcount
assert updated==1, updated
os._exit(74)
"""
        child = subprocess.run(
            [sys.executable, "-c", script, self.path,
             self.claim[1], str(self.claim[3])],
            check=False, capture_output=True, text=True, timeout=12,
        )
        self.assertEqual(child.returncode, 74, child.stderr)
        self.assertEqual(
            OfflineAtomicCoordinator(self.path).inspect(**SCOPE)[4],
            "reserved",
        )
        decisions = self.competing_processes()
        self.assertEqual(
            sum(state == "observed_unverified" for state, _, _ in decisions),
            1, decisions,
        )
        self.assertEqual(sum(count for _, count, _ in decisions), 1)
        self.assertEqual(
            OfflineAtomicCoordinator(self.path).inspect(**SCOPE)[4],
            "dispatch_unknown",
        )


if __name__ == "__main__":
    unittest.main()
