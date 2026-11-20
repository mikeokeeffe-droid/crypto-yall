"""Offline-only paginated exchange evidence gate for synthetic reconciliation.

This adapter plugs into BOTH offline inspection flows. An injected snapshot
reader supplies positions and order summaries, and an independent-style
page reader supplies bounded fill and open-order pages. A snapshot is rejected
if paginated records differ from its claims, any page is incomplete, or the
page snapshot identity/time disagrees with the capture.

This is NOT a live exchange adapter and DOES NOT authenticate either source.
Matching fake page data is not evidence of real provenance, atomicity, or
permission to release a fence, submit orders, or transfer ownership.
"""
from copy import deepcopy

from offline_exchange_page_review import collect_exchange_records


class _CaptureBoundPages:
    def __init__(self, source, capture_id, timestamp):
        self.source = source
        self.capture_id = capture_id
        self.timestamp = timestamp

    def fetch_page(self, *, account, coin, kind, cursor):
        result = self.source.fetch_page(
            account=account, coin=coin, kind=kind, cursor=cursor,
            capture_id=self.capture_id,
        )
        # Prevent a complete page from a different capture (or time) from
        # being laundered into the current snapshot's completeness claim.
        if (type(result) is not dict
                or result.get("snapshot_id") != self.capture_id
                or result.get("observed_at_ms") != self.timestamp):
            raise ValueError("page does not belong to this capture")
        return result


class PaginatedOfflineExchangeEvidence:
    """Strict fake-data adapter for existing read-only inspection functions.

    The wrapped snapshot_reader must provide read_order and
    capture_position_orders_fills. page_reader must provide fetch_page with
    a capture_id argument. No network or client configuration is included.
    """

    def __init__(self, *, snapshot_reader, page_reader, max_pages=8,
                 max_records=1000):
        self.snapshot_reader = snapshot_reader
        self.page_reader = page_reader
        self.max_pages = max_pages
        self.max_records = max_records

    def read_order(self, *, account, order_id):
        return self.snapshot_reader.read_order(
            account=account, order_id=order_id,
        )

    def capture_position_orders_fills(self, *, account, coin):
        capture = self.snapshot_reader.capture_position_orders_fills(
            account=account, coin=coin,
        )
        if (type(capture) is not dict
                or capture.get("account") != account
                or capture.get("coin") != coin
                or capture.get("complete") is not True
                or capture.get("fills_complete") is not True
                or capture.get("fresh") is not True
                or type(capture.get("capture_id")) is not str
                or not capture["capture_id"].strip()
                or type(capture.get("observed_at_ms")) is not int
                or capture["observed_at_ms"] <= 0
                or type(capture.get("fills")) is not list
                or type(capture.get("open_orders")) is not list):
            raise ValueError("unverifiable capture completeness")

        pages = _CaptureBoundPages(
            self.page_reader, capture["capture_id"],
            capture["observed_at_ms"],
        )
        for kind in ("fills", "open_orders"):
            result = collect_exchange_records(
                reader=pages, account=account, coin=coin, kind=kind,
                max_pages=self.max_pages, max_records=self.max_records,
            )
            if result.status != "complete_record_set":
                raise ValueError("incomplete or inconsistent " + kind)
            if list(result.records) != capture[kind]:
                raise ValueError("snapshot differs from paginated " + kind)
        # Never mark existing evidence authentic or upgrade statuses.
        return deepcopy(capture)
