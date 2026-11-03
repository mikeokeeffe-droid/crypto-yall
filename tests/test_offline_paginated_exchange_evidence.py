"""Fake-only tests: paginated records gate existing no-fill recovery path."""
import copy
import unittest

from offline_independent_entry_reconciler import inspect_unresolved_entry
from offline_paginated_exchange_evidence import PaginatedOfflineExchangeEvidence


class FakeIntent:
    def __init__(self):
        self.intent = dict(
            bot="daily", coin="SOL", token="test-token", status="uncertain",
            exchange_order_id="order-1", submitted_at_ms=90_000,
            requested_size=0.25,
        )

    def read_intent(self, **kwargs):
        return dict(self.intent)


class FakeSnapshots:
    def __init__(self):
        self.calls = 0

    def read_order(self, **kwargs):
        return dict(
            account="test-account", coin="SOL", order_id="order-1",
            final=True, status="rejected", complete=True, filled_size=0,
        )

    def capture_position_orders_fills(self, **kwargs):
        self.calls += 1
        n = self.calls
        return dict(
            account="test-account", coin="SOL", capture_id="capture-" + str(n),
            fresh=True, complete=True, fills_complete=True,
            observed_at_ms=94_000 + n * 1000, position_size=0,
            fills=[], open_orders=[],
        )


class FakePages:
    def __init__(self):
        self.fail_kind = None
        self.fail_capture = None
        self.fake_fill = False
        self.foreign_account = False
        self.extra_cursor = False
        self.calls = []

    def fetch_page(self, *, account, coin, kind, cursor, capture_id):
        self.calls.append((kind, cursor, capture_id))
        idx = int(capture_id.rsplit("-", 1)[1])
        if self.fail_kind == kind and self.fail_capture == idx:
            raise TimeoutError("incomplete fake page")
        records = []
        if self.fake_fill and kind == "fills":
            records = [dict(account=account, coin=coin, fill_id="unexpected")]
        if self.foreign_account and kind == "open_orders":
            account = "foreign-account"
        return dict(
            account=account, coin=coin, kind=kind,
            request_cursor=cursor, next_cursor=("more" if self.extra_cursor else None),
            snapshot_id=capture_id, observed_at_ms=94_000 + idx * 1000,
            complete=True, records=records,
        )


class PaginatedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.pages = FakePages()
        self.snapshots = FakeSnapshots()
        self.intent = FakeIntent()

    def review(self):
        adapter = PaginatedOfflineExchangeEvidence(
            snapshot_reader=self.snapshots, page_reader=self.pages,
            max_pages=3,
        )
        return inspect_unresolved_entry(
            intent_reader=self.intent, exchange_reader=adapter,
            bot="daily", coin="SOL", token="test-token",
            account="test-account", now_ms=100_000,
        )

    def test_matching_fake_pages_only_allow_review_candidate(self):
        result = self.review()
        self.assertEqual(result.status, "review_candidate")
        self.assertEqual(len(self.pages.calls), 4)

    def test_missing_pages_hold_even_when_snapshots_claim_complete(self):
        self.pages.fail_kind = "fills"
        self.pages.fail_capture = 2
        self.assertEqual(self.review().status, "hold")

    def test_foreign_order_page_holds(self):
        self.pages.foreign_account = True
        self.assertEqual(self.review().status, "hold")

    def test_unexpected_fill_blocks_no_fill_candidate(self):
        self.pages.fake_fill = True
        self.assertEqual(self.review().status, "hold")

    def test_unterminated_pagination_holds(self):
        self.pages.extra_cursor = True
        self.assertEqual(self.review().status, "hold")


if __name__ == "__main__":
    unittest.main()
