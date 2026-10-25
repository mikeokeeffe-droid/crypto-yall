"""Read-only Hyperliquid fill evidence with bounded time-window pagination.

Never infer completeness from a single user_fills response. This helper only
supports an injected Info client exposing user_fills_by_time and does not
write to an exchange or database.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class FillWindow:
    fills: list
    complete: bool
    reason: str

def fetch_fills_window(info, address, start_ms, end_ms, *, max_pages=20, page_limit=2000):
    if not isinstance(start_ms, int) or not isinstance(end_ms, int) or start_ms < 0 or end_ms <= start_ms:
        return FillWindow([], False, "invalid time window")
    if not 1 <= max_pages <= 100 or not 1 <= page_limit <= 2000:
        return FillWindow([], False, "invalid limits")
    cursor = start_ms
    all_fills = []
    seen = set()
    for _ in range(max_pages):
        try:
            page = info.user_fills_by_time(address, cursor, end_ms)
        except Exception:
            return FillWindow([], False, "exchange request failed")
        if not isinstance(page, list) or len(page) > page_limit:
            return FillWindow([], False, "invalid or oversized page")
        last_time = None
        for fill in page:
            if not isinstance(fill, dict) or not isinstance(fill.get("time"), int):
                return FillWindow([], False, "invalid fill timestamp")
            timestamp = fill["time"]
            if timestamp < cursor or timestamp > end_ms:
                return FillWindow([], False, "out-of-range fill timestamp")
            if last_time is not None and timestamp < last_time:
                return FillWindow([], False, "nonmonotonic fill timestamps")
            last_time = timestamp
            identity = (fill.get("tid"), fill.get("oid"), timestamp)
            if identity in seen or identity[0] is None:
                return FillWindow([], False, "duplicate or missing trade identity")
            seen.add(identity)
            all_fills.append(fill)
        if len(page) < page_limit:
            return FillWindow(all_fills, True, "window fetched")
        # A full page ending with multiple fills at one millisecond cannot
        # be safely advanced without an exchange-provided cursor.
        if last_time is None:
            return FillWindow([], False, "missing page cursor")
        if sum(f.get("time") == last_time for f in page) > 1:
            return FillWindow([], False, "ambiguous timestamp page boundary")
        cursor = last_time + 1
        if cursor > end_ms:
            return FillWindow(all_fills, True, "window fetched")
    return FillWindow([], False, "page budget exhausted")
