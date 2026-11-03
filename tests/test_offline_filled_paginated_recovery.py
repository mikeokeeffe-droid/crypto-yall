"""Fake-only filled-ownership recovery tests using bounded paginated evidence.

Never creates a real exchange client, order, database connection, or release.
A synthetic 'handoff_candidate' is not ownership approval or live provenance.
"""
import copy
import unittest

from offline_filled_recovery_inspection import inspect_possible_filled_recovery
from offline_paginated_exchange_evidence import PaginatedOfflineExchangeEvidence


ACCOUNT = "test-account"
COIN = "SOL"


def fake_fill(fill_id="fill-1", size="2"):
    return dict(account=ACCOUNT, coin=COIN, order_id="123",
                side="long", fill_id=fill_id, size=size, time_ms=100_100)


def fake_capture(name, timestamp, fills):
    return dict(account=ACCOUNT, coin=COIN, capture_id=name,
                fresh=True, complete=True, fills_complete=True,
                observed_at_ms=timestamp, position_size="2",
                open_orders=[], fills=copy.deepcopy(fills))


class FakeIntentReader:
    def __init__(self):
        self.intent = dict(bot="daily", coin=COIN, token="claim-1",
                           fence_token=42, status="uncertain",
                           action="open_long", exchange_order_id="123",
                           submitted_at_ms=100_000, requested_size="2")
        self.before = dict(account=ACCOUNT, coin=COIN, bot="daily",
                           token="claim-1", fence_token=42, capture_id="pre",
                           observed_at_ms=99_000, position_size="0",
                           fresh=True, complete=True, open_orders=[])
        self.intent_reads = 0
        self.baseline_reads = 0

    def read_intent(self, **kwargs):
        self.intent_reads += 1
        return copy.deepcopy(self.intent)

    def read_pre_submit_capture(self, **kwargs):
        self.baseline_reads += 1
        return copy.deepcopy(self.before)


class FakeSnapshots:
    def __init__(self):
        fill = fake_fill()
        self.captures = [
            fake_capture("first", 101_000, [fill]),
            fake_capture("second", 102_000, [fill]),
        ]
        self.order = dict(account=ACCOUNT, coin=COIN, order_id="123",
                          side="long", status="filled", final=True,
                          complete=True, filled_size="2")
        self.capture_reads = 0
        self.order_reads = 0

    def read_order(self, **kwargs):
        self.order_reads += 1
        return copy.deepcopy(self.order)

    def capture_position_orders_fills(self, **kwargs):
        index = self.capture_reads
        self.capture_reads += 1
        return copy.deepcopy(self.captures[min(index, 1)])


class FakePages:
    def __init__(self, snapshots):
        self.pages = {}
        self.calls = []
        for capture in snapshots.captures:
            for kind in ("fills", "open_orders"):
                self.add_page(capture, kind, None, None, capture[kind])

    def add_page(self, capture, kind, cursor, next_cursor, records):
        key = (capture["capture_id"], kind, cursor)
        self.pages[key] = dict(
            account=ACCOUNT, coin=COIN, kind=kind, request_cursor=cursor,
            next_cursor=next_cursor, snapshot_id=capture["capture_id"],
            observed_at_ms=capture["observed_at_ms"], complete=True,
            records=copy.deepcopy(records),
        )

    def fetch_page(self, *, account, coin, kind, cursor, capture_id):
        key = (capture_id, kind, cursor)
        self.calls.append(key)
        if key not in self.pages:
            raise TimeoutError("synthetic page unavailable")
        return copy.deepcopy(self.pages[key])


class FilledPaginatedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.intents = FakeIntentReader()
        self.snapshots = FakeSnapshots()
        self.pages = FakePages(self.snapshots)

    def review(self):
        evidence = PaginatedOfflineExchangeEvidence(
            snapshot_reader=self.snapshots, page_reader=self.pages,
            max_pages=3, max_records=20,
        )
        return inspect_possible_filled_recovery(
            intent_reader=self.intents, exchange_reader=evidence,
            bot="daily", coin=COIN, token="claim-1",
            expected_fence_token=42, account=ACCOUNT, now_ms=103_000,
        )

    def test_complete_fake_fill_is_only_handoff_candidate(self):
        result = self.review()
        self.assertEqual(result.status, "handoff_candidate")
        self.assertEqual(self.intents.intent_reads, 2)
        self.assertEqual(self.intents.baseline_reads, 2)
        self.assertEqual(self.snapshots.order_reads, 2)
        self.assertEqual(self.snapshots.capture_reads, 2)
        self.assertEqual(len(self.pages.calls), 4)

    def test_two_page_fills_can_match_without_authorizing_handoff(self):
        fills = [fake_fill("fill-1", "1"), fake_fill("fill-2", "1")]
        for capture in self.snapshots.captures:
            capture["fills"] = copy.deepcopy(fills)
            self.pages.add_page(capture, "fills", None, "page-2", [fills[0]])
            self.pages.add_page(capture, "fills", "page-2", None, [fills[1]])
        self.assertEqual(self.review().status, "handoff_candidate")
        self.assertEqual(len(self.pages.calls), 6)

    def test_missing_fill_page_fails_closed(self):
        self.pages.pages[("second", "fills", None)]["next_cursor"] = "missing"
        self.assertEqual(self.review().status, "hold")

    def test_conflicting_snapshot_identity_or_timestamp_fails_closed(self):
        for changes in ({"snapshot_id": "old-capture"},
                        {"observed_at_ms": 99_000}):
            with self.subTest(changes=changes):
                self.setUp()
                self.pages.pages[("first", "fills", None)].update(changes)
                self.assertEqual(self.review().status, "hold")

    def test_paginated_extra_fill_cannot_be_laundered_by_snapshot(self):
        self.pages.pages[("first", "fills", None)]["records"].append(
            fake_fill("unseen-fill", "1"))
        self.assertEqual(self.review().status, "hold")

    def test_open_order_page_mismatch_fails_closed(self):
        self.pages.pages[("first", "open_orders", None)]["records"] = [
            dict(account=ACCOUNT, coin=COIN, order_id="unexpected-order")
        ]
        self.assertEqual(self.review().status, "hold")

    def test_duplicate_fills_across_pages_fail_closed(self):
        first = self.snapshots.captures[0]
        self.pages.add_page(first, "fills", None, "second-page", [fake_fill()])
        self.pages.add_page(first, "fills", "second-page", None, [fake_fill()])
        self.assertEqual(self.review().status, "hold")

    def test_incomplete_second_open_order_page_fails_closed(self):
        self.pages.pages[("second", "open_orders", None)]["complete"] = False
        self.assertEqual(self.review().status, "hold")

    def test_no_durable_baseline_never_attempts_exchange_recovery(self):
        self.intents.before = None
        self.assertEqual(self.review().status, "hold")
        self.assertEqual(self.snapshots.order_reads, 0)
        self.assertEqual(self.pages.calls, [])


if __name__ == "__main__":
    unittest.main()
