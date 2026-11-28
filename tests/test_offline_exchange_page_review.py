"""Fake-only tests for bounded exchange record pagination. No credentials."""
import copy
import unittest

from offline_exchange_page_review import collect_exchange_records


ACCOUNT = "test-account"
COIN = "SOL"


def page(cursor=None, next_cursor=None, kind="fills", records=None,
         snapshot_id="snapshot-1", observed_at_ms=100_000, **changes):
    if records is None:
        records = [{"account": ACCOUNT, "coin": COIN, "fill_id": "fill-1"}]
    result = dict(
        account=ACCOUNT, coin=COIN, kind=kind,
        request_cursor=cursor, next_cursor=next_cursor,
        snapshot_id=snapshot_id, observed_at_ms=observed_at_ms,
        complete=True, records=records,
    )
    result.update(changes)
    return result


class FakePageReader:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def fetch_page(self, *, account, coin, kind, cursor):
        self.calls.append((account, coin, kind, cursor))
        if not self.pages:
            raise TimeoutError("no more fake pages")
        return copy.deepcopy(self.pages.pop(0))


class ExchangePageReviewTests(unittest.TestCase):
    def inspect(self, pages, **kwargs):
        reader = FakePageReader(pages)
        result = collect_exchange_records(
            reader=reader, account=ACCOUNT, coin=COIN, kind="fills", **kwargs
        )
        return result, reader

    def test_single_complete_page_is_synthetic_only(self):
        result, reader = self.inspect([page()])
        self.assertEqual(result.status, "complete_record_set")
        self.assertEqual(len(result.records), 1)
        self.assertEqual(reader.calls, [(ACCOUNT, COIN, "fills", None)])

    def test_two_pages_must_finish_same_snapshot(self):
        result, reader = self.inspect([
            page(next_cursor="second"),
            page(cursor="second", records=[
                {"account": ACCOUNT, "coin": COIN, "fill_id": "fill-2"}
            ]),
        ])
        self.assertEqual(result.status, "complete_record_set")
        self.assertEqual(len(result.records), 2)
        self.assertEqual(reader.calls[-1][-1], "second")

    def test_missing_terminal_page_and_cursor_replay_block(self):
        cases = (
            [page(next_cursor="more")],
            [page(next_cursor="more"), page(cursor="wrong")],
            [page(next_cursor="more"),
             page(cursor="more", next_cursor="more")],
            [page(next_cursor="a"),
             page(cursor="a", next_cursor="b"),
             page(cursor="b", next_cursor="a")],
        )
        for pages in cases:
            with self.subTest(pages=pages):
                self.assertEqual(self.inspect(pages)[0].status, "hold")

    def test_snapshot_identity_change_blocks(self):
        for change in (
            {"snapshot_id": "different"},
            {"observed_at_ms": 101_000},
            {"account": "other"},
            {"coin": "BTC"},
            {"kind": "open_orders"},
            {"complete": False},
        ):
            with self.subTest(change=change):
                self.assertEqual(self.inspect([
                    page(next_cursor="next"),
                    page(cursor="next", records=[], **change),
                ])[0].status, "hold")

    def test_duplicate_or_foreign_records_block(self):
        for record in (
            {"account": ACCOUNT, "coin": COIN, "fill_id": "fill-1"},
            {"account": "other", "coin": COIN, "fill_id": "fill-2"},
            {"account": ACCOUNT, "coin": "BTC", "fill_id": "fill-2"},
            {"account": ACCOUNT, "coin": COIN},
        ):
            with self.subTest(record=record):
                self.assertEqual(self.inspect([
                    page(next_cursor="next"),
                    page(cursor="next", records=[record]),
                ])[0].status, "hold")

    def test_limits_or_missing_metadata_block(self):
        for pages, opts in (
            ([page(next_cursor="next"), page(cursor="next", records=[])],
             {"max_pages": 1}),
            ([page()], {"max_records": 0}),
            ([page()], {"max_records": 1, "max_pages": 0}),
            ([page(records=[{"account": ACCOUNT, "coin": COIN, "fill_id": "fill-1"},
                            {"account": ACCOUNT, "coin": COIN, "fill_id": "fill-2"}])],
             {"max_records": 1}),
            ([page(snapshot_id="")], {}),
            ([page(observed_at_ms=0)], {}),
        ):
            with self.subTest(opts=opts, pages=pages):
                self.assertEqual(self.inspect(pages, **opts)[0].status, "hold")

    def test_open_orders_require_order_ids(self):
        reader = FakePageReader([page(
            kind="open_orders",
            records=[{"account": ACCOUNT, "coin": COIN, "order_id": "order-1"}],
        )])
        accepted = collect_exchange_records(
            reader=reader, account=ACCOUNT, coin=COIN, kind="open_orders"
        )
        self.assertEqual(accepted.status, "complete_record_set")
        reader = FakePageReader([page(kind="open_orders")])
        rejected = collect_exchange_records(
            reader=reader, account=ACCOUNT, coin=COIN, kind="open_orders"
        )
        self.assertEqual(rejected.status, "hold")

    def test_timeout_and_malformed_page_block(self):
        for bad in ([], [None], [page(next_cursor="next")]):
            with self.subTest(bad=bad):
                self.assertEqual(self.inspect(bad)[0].status, "hold")


if __name__ == "__main__":
    unittest.main()
