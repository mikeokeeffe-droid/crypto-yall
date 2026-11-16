"""OFFLINE testnet /info snapshot validation primitives; ALWAYS HOLD.

No HTTP implementation, signer, wallet, keys, or network activation is
included. A boolean argument cannot enable networking. The helper parsers
inspect untrusted caller-supplied documents only. All permissions remain
false; a future authorized collector requires a separate reviewed change.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re

_URL = "https://api.hyperliquid-testnet.xyz/info"
_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z", re.ASCII)
_COIN = re.compile(r"[A-Z][A-Z0-9]{0,23}\Z", re.ASCII)
_SIZE = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,12})?\Z", re.ASCII)
_LIMIT = 1048576


@dataclass(frozen=True)
class ReadOnlyTestnetSnapshot:
    state: str = "HOLD"
    reason: str = "read-only testnet network access not approved"
    snapshot_consistent: bool = False
    positions_digest: str | None = None
    position_count: int = 0
    open_order_count: int = 0
    # Raw public position sizes for future read-only reconciliation; never
    # trusted as provenance or permission. Excluded from repr to avoid logs.
    observed_positions: tuple = field(default=(), repr=False)
    # No source of operational authority exists here.
    account_ownership_verified: bool = False
    historical_completeness_verified: bool = False
    fills_reconciled: bool = False
    position_ownership_verified: bool = False
    runtime_identity_authenticated: bool = False
    replay_consumed: bool = False
    journal_recorded: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def _positions(document):
    if (type(document) is not dict
            or type(document.get("assetPositions")) is not list
            or len(document["assetPositions"]) > 500):
        raise ValueError("invalid position document")
    positions = {}
    for record in document["assetPositions"]:
        if type(record) is not dict or type(record.get("position")) is not dict:
            raise ValueError("invalid position record")
        pos = record["position"]
        coin, size = pos.get("coin"), pos.get("szi")
        if (type(coin) is not str or _COIN.fullmatch(coin) is None
                or coin in positions or type(size) is not str
                or _SIZE.fullmatch(size) is None):
            raise ValueError("duplicate/invalid asset")
        try:
            amount = Decimal(size)
        except InvalidOperation:
            raise ValueError("invalid position amount") from None
        if not amount.is_finite() or amount == 0 or abs(amount) > 1000000000:
            raise ValueError("invalid position amount")
        positions[coin] = format(amount.normalize(), "f")
    return positions


def _orders(document):
    if type(document) is not list or len(document) > 5000:
        raise ValueError("invalid open orders document")
    orders = {}
    for order in document:
        if type(order) is not dict:
            raise ValueError("invalid order record")
        oid, coin, side, size = (
            order.get("oid"), order.get("coin"),
            order.get("side"), order.get("sz"),
        )
        if (type(oid) is not int or oid <= 0 or oid in orders
                or type(coin) is not str or _COIN.fullmatch(coin) is None
                or side not in ("A", "B")
                or type(size) is not str or _SIZE.fullmatch(size) is None
                or Decimal(size) < 0):
            raise ValueError("invalid/duplicate order")
        # A zero-sized open order is possible in the provider response;
        # the presence of ANY order, regardless of quantity, blocks readiness.
        orders[oid] = (coin, side, format(Decimal(size).normalize(), "f"))
    return orders


def inspect_testnet_info_readonly_snapshot(
    *, configured_public_account, enabled_readonly_testnet_network=False,
):
    """Deliberately inert compatibility API, regardless of any caller input.

    This draft cannot make a public /info request or certify a snapshot.
    To add transport requires a separate reviewed code change and explicit
    approval following independent host/runtime/network security assessment.
    """
    return ReadOnlyTestnetSnapshot()
