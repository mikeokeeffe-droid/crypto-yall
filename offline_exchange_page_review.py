"""Offline pagination guard for independently fetched exchange records.

No network clients, authentication, credentials, orders, or database writes.
An injected read-only provider supplies fake pages in CI. Matching fields,
snapshots and a completed pagination chain are NOT proof of exchange origin.
This module can report only a complete *synthetic* record set or a hold.
It cannot authorize a position handoff, release a fence, or submit an order.
"""
from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True)
class RecordPageReview:
    status: str
    reason: str
    records: tuple = ()


def collect_exchange_records(*, reader, account, coin, kind,
                             max_pages=8, max_records=1000):
    """Reject gaps, replay, conflicting pages, duplicates and unbounded reads.

    Provider contract: fetch_page(account, coin, kind, cursor) returns a dict:
    account, coin, kind, request_cursor, snapshot_id, observed_at_ms,
    complete, records, next_cursor. A null next_cursor means end of dataset.
    All pages in one read must refer to a single stable snapshot identity.
    This checks claims supplied by the reader; authentication and complete
    exchange pagination still require an independently reviewed transport.
    """
    def hold(reason):
        return RecordPageReview("hold", reason)

    if (type(account) is not str or not account.strip()
            or type(coin) is not str or not coin
            or not coin.isascii() or not coin.isalnum()
            or coin != coin.upper()
            or kind not in ("fills", "open_orders")
            or type(max_pages) is not int or not 1 <= max_pages <= 20
            or type(max_records) is not int or not 1 <= max_records <= 10000
            or reader is None):
        return hold("invalid bounded read configuration")

    cursor = None
    seen_cursors = set()
    seen_ids = set()
    records = []
    baseline = None
    id_key = "fill_id" if kind == "fills" else "order_id"

    for _ in range(max_pages):
        try:
            page = reader.fetch_page(
                account=account, coin=coin, kind=kind, cursor=cursor)
        except Exception:
            return hold("page read failed or timed out")
        if (type(page) is not dict
                or page.get("account") != account
                or page.get("coin") != coin
                or page.get("kind") != kind
                or "request_cursor" not in page
                or page["request_cursor"] != cursor
                or page.get("complete") is not True
                or type(page.get("records")) is not list
                or "next_cursor" not in page):
            return hold("page is incomplete or mismatched")
        snapshot_id = page.get("snapshot_id")
        timestamp = page.get("observed_at_ms")
        if (type(snapshot_id) is not str or not snapshot_id.strip()
                or type(timestamp) is not int or timestamp <= 0):
            return hold("missing snapshot provenance fields")
        current = (snapshot_id, timestamp)
        if baseline is None:
            baseline = current
        elif current != baseline:
            return hold("paginated snapshot changed mid-read")

        batch = page["records"]
        if len(records) + len(batch) > max_records:
            return hold("record count limit exceeded")
        for item in batch:
            if (type(item) is not dict
                    or item.get("coin") != coin
                    or item.get("account") != account
                    or type(item.get(id_key)) is not str
                    or not item[id_key].strip()):
                return hold("missing or foreign record identity")
            record_id = item[id_key]
            if record_id in seen_ids:
                return hold("duplicate record across pages")
            seen_ids.add(record_id)
            records.append(deepcopy(item))

        next_cursor = page["next_cursor"]
        if next_cursor is None:
            return RecordPageReview(
                "complete_record_set",
                "bounded synthetic pages exhausted; source not authenticated",
                tuple(records),
            )
        if (type(next_cursor) is not str or not next_cursor.strip()
                or next_cursor == cursor or next_cursor in seen_cursors):
            return hold("invalid or replayed pagination cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    return hold("pagination did not finish within page limit")
