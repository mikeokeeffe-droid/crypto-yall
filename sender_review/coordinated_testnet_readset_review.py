"""Coordinated six-frame synthetic /info read-set review; always HOLD.

Combines the EXISTING position, open-order and bounded history validators
without opening any network connections or introducing an exchange signer.
This is a read-only parser of supplied untrusted documents, not an atomic
exchange snapshot, account provenance proof, or trading authorization.
Workflow integration and live client credentials are intentionally absent.
"""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json

from sender_review.hyperliquid_testnet_readonly_snapshot_review import (
    _positions, _orders,
)
from sender_review.hyperliquid_testnet_recent_history_review import (
    inspect_recent_history_documents_offline, _fills,
)


@dataclass(frozen=True)
class CoordinatedReadsetReview:
    state: str = "HOLD"
    reason: str = "untrusted review-only documents"
    locally_consistent: bool = False
    observed_positions_sha256: str | None = None
    observed_position_count: int = 0
    reviewed_order_count: int = 0
    reviewed_fill_count: int = 0
    # Local arithmetic comparison only, never a trusted historical baseline.
    bounded_fill_net_matches_positions: bool = False
    # ALWAYS false: this is no source of host, historical, or trading trust.
    network_performed: bool = False
    exchange_origin_authenticated: bool = False
    account_scope_verified: bool = False
    history_complete: bool = False
    from_flat_baseline_verified: bool = False
    bot_position_ownership_verified: bool = False
    durable_fence_reserved: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def inspect_coordinated_readset_offline(
    *, positions_before, open_orders_before,
    historical_orders, user_fills, open_orders_after,
    positions_after, start_time_ms, end_time_ms,
):
    """Review exactly six staged read-only data frames, without I/O.

    Intervening fills and missing pre-window history remain possible even if
    all supplied documents match. Runtime must separately pin the account,
    capture provable TLS origin and establish a trusted flat baseline.
    """
    hold = CoordinatedReadsetReview()
    try:
        before = _positions(positions_before)
        after = _positions(positions_after)
        orders_first = _orders(open_orders_before)
        orders_last = _orders(open_orders_after)
        if before != after or orders_first != orders_last:
            return CoordinatedReadsetReview(reason="positions/orders changed")
        if orders_first:
            return CoordinatedReadsetReview(
                reason="open orders outstanding; account state unsettled",
            )
        history = inspect_recent_history_documents_offline(
            historical_document=historical_orders,
            fills_document=user_fills,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )
        if (history.state != "RECENT_TESTNET_HISTORY_REVIEW_ONLY_HOLD"
                or not history.recent_records_consistent):
            return CoordinatedReadsetReview(
                reason="historical order/fill evidence incomplete or conflicting",
            )
        # A bounded order/fill sample can be internally consistent while
        # accounting for only part of the current exposure. Require the
        # signed net of those sample fills to match observed positions before
        # describing the six-frame fixture as *locally* coherent. No such
        # match establishes a true historical flat baseline or ownership.
        grouped_fills, _ = _fills(
            user_fills, start_time_ms=start_time_ms, end_time_ms=end_time_ms,
        )
        net = {}
        for entries in grouped_fills.values():
            for coin, side, amount in entries:
                delta = amount if side == "B" else -amount
                net[coin] = net.get(coin, Decimal("0")) + delta
        nonzero_net = {coin: value for coin, value in net.items() if value != 0}
        observed = {coin: Decimal(size) for coin, size in before.items()}
        if nonzero_net != observed:
            return CoordinatedReadsetReview(
                reason="bounded fill net disagrees with position snapshot; "
                       "older activity or missing events possible",
            )
        digest = hashlib.sha256(json.dumps(
            before, sort_keys=True, separators=(",", ":"),
        ).encode("ascii")).hexdigest()
        return CoordinatedReadsetReview(
            state="COHERENT_SIX_FRAME_FIXTURE_HOLD",
            reason="six frames locally consistent only; not an atomic read "
                   "or an authenticated complete account ownership history",
            locally_consistent=True,
            bounded_fill_net_matches_positions=True,
            observed_positions_sha256=digest,
            observed_position_count=len(before),
            reviewed_order_count=history.recent_order_count,
            reviewed_fill_count=history.recent_fill_count,
        )
    except (ValueError, TypeError, OverflowError, UnicodeError):
        return hold
