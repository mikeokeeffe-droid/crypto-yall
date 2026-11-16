"""Coordinated six-frame synthetic /info read-set review; always HOLD.

Combines the EXISTING position, open-order and bounded history validators
without introducing an exchange signer. Its offline parser does NO I/O.
A separate opt-in wrapper reuses the existing pinned read-only testnet
transport, but is never invoked by existing workflows or deployed services.
Neither path proves an atomic exchange snapshot, account provenance or
trading authorization. Live client credentials are intentionally absent.
"""
from dataclasses import dataclass, replace
from decimal import Decimal
import hashlib
import json
import ssl
import urllib.request

from sender_review.hyperliquid_testnet_readonly_snapshot_review import (
    _positions, _orders, _ACCOUNT, _NoRedirect, _info_query,
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
    # True only when opt-in transport attempts public reads; not proof of origin.
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


def inspect_coordinated_testnet_readset_transport_review(
    *, configured_public_account, start_time_ms, end_time_ms,
    enabled_readonly_testnet_network=False,
):
    """Optional six-request testnet read, OFF by default and always HOLD.

    Reuses one fixed HTTPS /info reader. No user-chosen endpoint, API key,
    signer, DB, /exchange route or order transport. A boolean can request
    transport but cannot establish actual operator permission, egress
    isolation, TLS-origin attestation, or history provenance. No existing
    server or trading job calls this function.
    """
    denied = CoordinatedReadsetReview()
    if (enabled_readonly_testnet_network is not True
            or type(configured_public_account) is not str
            or _ACCOUNT.fullmatch(configured_public_account) is None
            or type(start_time_ms) is not int
            or type(end_time_ms) is not int
            or not 0 <= start_time_ms < end_time_ms <= 9007199254740991
            or end_time_ms - start_time_ms > 86400000):
        return denied
    # NETWORK ACCESS REQUIRES INDEPENDENT PRE-DEPLOYMENT SECURITY REVIEW
    # AND EXPLICIT OPERATOR APPROVAL. Never enable via a live workflow.
    attempted = replace(denied, network_performed=True,
                        reason="testnet read attempt failed; HOLD")
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        types = (
            "clearinghouseState", "openOrders", "historicalOrders",
            "userFillsByTime", "openOrders", "clearinghouseState",
        )
        documents = []
        for kind in types:
            kwargs = {"account": configured_public_account, "kind": kind}
            if kind == "userFillsByTime":
                kwargs.update(
                    start_time_ms=start_time_ms, end_time_ms=end_time_ms,
                )
            documents.append(_info_query(opener, **kwargs))
        result = inspect_coordinated_readset_offline(
            positions_before=documents[0],
            open_orders_before=documents[1],
            historical_orders=documents[2], user_fills=documents[3],
            open_orders_after=documents[4], positions_after=documents[5],
            start_time_ms=start_time_ms, end_time_ms=end_time_ms,
        )
        if not result.locally_consistent:
            return replace(result, network_performed=True)
        return replace(
            result, network_performed=True,
            state="OBSERVED_TESTNET_READSET_REVIEW_ONLY_HOLD",
            reason="pinned testnet /info frames locally coherent; NO runtime "
                   "provenance, complete history, position ownership or trades",
        )
    except (ValueError, TypeError, UnicodeError, OSError, OverflowError):
        return attempted
