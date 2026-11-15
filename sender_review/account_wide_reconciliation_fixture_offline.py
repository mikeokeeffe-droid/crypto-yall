"""Synthetic account-wide position ownership reconciliation, offline ONLY.

Fixtures are NOT trusted exchange records or workload identities. Never
connects to a network/database, imports an executor/signer, sends orders,
releases fences or claims that a close is safe. EVERY result is HOLD.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re

from sender_review.proposed_intent_interfaces_offline import (
    inspect_proposed_intent_offline,
)

_ACCOUNT = "0x" + "1" * 40
_BOTS = frozenset(("daily", "intraday", "aggressive"))
_UNRESOLVED = frozenset(("open", "partial", "unknown_ack", "not_sent"))
_SETTLED = frozenset(("filled", "canceled"))
_ID = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_CLOID = re.compile(r"0x[0-9a-f]{32}\Z", re.ASCII)
_COIN = re.compile(r"[A-Z][A-Z0-9]{0,23}\Z", re.ASCII)
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?\Z", re.ASCII)


@dataclass(frozen=True)
class SyntheticPosition:
    account: str
    coin: str
    signed_size: str
    position_ref: str


@dataclass(frozen=True)
class SyntheticOrder:
    account: str
    oid: str
    cloid: str
    nonce: str
    bot: str
    coin: str
    position_ref: str
    side: str  # buy or sell
    requested_size: str
    status: str
    fence: int


@dataclass(frozen=True)
class SyntheticFill:
    fill_id: str
    oid: str
    size: str


@dataclass(frozen=True)
class SyntheticClaim:
    bot: str
    coin: str
    position_ref: str
    order_ids: tuple[str, ...]
    fence: int


@dataclass(frozen=True)
class SyntheticAccountHistory:
    account: str
    sampled_epoch: int
    positions_complete: bool
    orders_complete: bool
    fills_complete: bool
    from_flat_baseline: bool
    positions: tuple[SyntheticPosition, ...]
    orders: tuple[SyntheticOrder, ...]
    fills: tuple[SyntheticFill, ...]
    claims: tuple[SyntheticClaim, ...]


@dataclass(frozen=True)
class ReconciliationReview:
    state: str = "HOLD"
    reason: str = "unauthenticated fixture; no close authority"
    fixture_consistent: bool = False
    fixture_net_size: str | None = None
    fixture_attributed_bot: str | None = None
    runtime_identity_authenticated: bool = False
    account_scope_verified: bool = False
    exchange_provenance_verified: bool = False
    ownership_verified: bool = False
    nonce_consumed: bool = False
    fence_released: bool = False
    reduce_only_verified: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    retry_authorized: bool = False
    signing_enabled: bool = False


def _num(value, *, signed=False):
    if type(value) is not str or not 0 < len(value) <= 32 or not _NUMBER.fullmatch(value):
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or abs(number) > Decimal("1000000"):
        return None
    if not signed and number <= 0:
        return None
    return number


def _matches(text, pattern):
    return type(text) is str and pattern.fullmatch(text) is not None


def _inspect_history(history, *, now_epoch, expected_account):
    if (
        type(history) is not SyntheticAccountHistory
        or expected_account != _ACCOUNT or history.account != _ACCOUNT
        or type(now_epoch) is not int or type(history.sampled_epoch) is not int
        or not 0 <= now_epoch - history.sampled_epoch <= 10
        or history.positions_complete is not True
        or history.orders_complete is not True
        or history.fills_complete is not True
        or history.from_flat_baseline is not True
        or any(type(v) is not tuple for v in (
            history.positions, history.orders, history.fills, history.claims
        ))
    ):
        return None, None, "incomplete-or-stale-account-wide-history"

    positions, orders, cloids, nonces = {}, {}, set(), set()
    for p in history.positions:
        if (
            type(p) is not SyntheticPosition or p.account != _ACCOUNT
            or not _matches(p.coin, _COIN)
            or not _matches(p.position_ref, _ID)
            or _num(p.signed_size, signed=True) is None
            or p.coin in positions
        ):
            return None, None, "invalid-or-duplicate-position"
        positions[p.coin] = p
    for o in history.orders:
        if (
            type(o) is not SyntheticOrder or o.account != _ACCOUNT
            or not _matches(o.coin, _COIN)
            or not _matches(o.oid, _ID) or not _matches(o.cloid, _CLOID)
            or not _matches(o.nonce, _ID)
            or not _matches(o.position_ref, _ID)
            or type(o.bot) is not str or o.bot not in _BOTS
            or o.side not in ("buy", "sell")
            or o.status not in _UNRESOLVED | _SETTLED
            or type(o.fence) is not int or o.fence <= 0
            or _num(o.requested_size) is None
            or o.oid in orders or o.cloid in cloids or o.nonce in nonces
            or o.coin not in positions
        ):
            return None, None, "unattributed-duplicate-or-invalid-order"
        orders[o.oid] = o
        cloids.add(o.cloid)
        nonces.add(o.nonce)
    if any(o.status in _UNRESOLVED for o in orders.values()):
        return None, None, "unresolved-account-wide-order"

    fills_seen = set()
    fill_totals = {oid: Decimal("0") for oid in orders}
    net = {coin: Decimal("0") for coin in positions}
    for f in history.fills:
        if (
            type(f) is not SyntheticFill
            or not _matches(f.fill_id, _ID) or f.fill_id in fills_seen
            or f.oid not in orders or _num(f.size) is None
        ):
            return None, None, "orphan-duplicate-or-invalid-fill"
        fills_seen.add(f.fill_id)
        o = orders[f.oid]
        q = _num(f.size)
        fill_totals[f.oid] += q
        net[o.coin] += q if o.side == "buy" else -q
    for oid, o in orders.items():
        filled = fill_totals[oid]
        if filled > _num(o.requested_size) or (
            o.status == "filled" and filled != _num(o.requested_size)
        ):
            return None, None, "inconsistent-order-fill-quantity"
        if o.status == "canceled" and filled > 0:
            # This conservative fixture cannot adjudicate partial cancels.
            return None, None, "partially-filled-cancelled-order"
    if any(net[coin] != _num(p.signed_size, signed=True)
           for coin, p in positions.items()):
        return None, None, "net-position-vs-fill-history-mismatch"

    claim_keys = set()
    for claim in history.claims:
        if (
            type(claim) is not SyntheticClaim
            or type(claim.bot) is not str or claim.bot not in _BOTS
            or not _matches(claim.coin, _COIN)
            or not _matches(claim.position_ref, _ID)
            or type(claim.order_ids) is not tuple
            or not all(_matches(oid, _ID) for oid in claim.order_ids)
            or len(set(claim.order_ids)) != len(claim.order_ids)
            or type(claim.fence) is not int or claim.fence <= 0
            or (claim.coin, claim.position_ref) in claim_keys
        ):
            return None, None, "conflicting-or-invalid-ownership-claims"
        claim_keys.add((claim.coin, claim.position_ref))
    return positions, orders, None


def reconcile_close_fixture_offline(
    *, body, fixture_bot, history, expected_account, expected_fence, now_epoch,
):
    """Return an illustrative, never-authorizing account-wide fixture verdict."""
    parsed = inspect_proposed_intent_offline(body=body, fixture_bot=fixture_bot)
    if parsed.state != "parsed_review_only_HOLD" or parsed.parsed_action != "protective_close":
        return ReconciliationReview(reason="invalid-protective-close-request")
    if type(expected_fence) is not int or expected_fence <= 0:
        return ReconciliationReview(reason="invalid-fence")
    try:
        request = json.loads(body)
    except (ValueError, TypeError):
        return ReconciliationReview()
    positions, orders, reason = _inspect_history(
        history, now_epoch=now_epoch, expected_account=expected_account
    )
    if reason:
        return ReconciliationReview(reason=reason)
    target = positions.get(request["coin"])
    if target is None or target.position_ref != request["position_ref"]:
        return ReconciliationReview(reason="target-position-ref-not-found")
    size = _num(target.signed_size, signed=True)
    requested = _num(request["close_size"])
    observed = _num(request["observed_position_size"])
    if (
        size is None or size == 0
        or request["side"] != ("long" if size > 0 else "short")
        or observed != abs(size) or requested is None or requested > abs(size)
    ):
        return ReconciliationReview(reason="size-or-position-side-mismatch")
    claims = [c for c in history.claims if (
        c.coin == target.coin and c.position_ref == target.position_ref
    )]
    if len(claims) != 1:
        return ReconciliationReview(reason="missing-or-ambiguous-claim")
    claim = claims[0]
    matched_orders = [o for o in orders.values() if o.coin == target.coin]
    ids = {o.oid for o in matched_orders}
    if (
        claim.bot != fixture_bot or claim.fence != expected_fence
        or not matched_orders or set(claim.order_ids) != ids
        or any(o.bot != fixture_bot or o.position_ref != target.position_ref
               or o.fence > expected_fence for o in matched_orders)
    ):
        return ReconciliationReview(reason="foreign-or-unattributed-position")
    # This is ONLY a consistent fake record, not a real position provenance.
    return ReconciliationReview(
        reason="synthetic-consistency-only; no real ownership verification",
        fixture_consistent=True,
        fixture_net_size=str(size),
        fixture_attributed_bot=fixture_bot,
    )
