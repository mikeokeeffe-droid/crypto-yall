"""Unwired, zero-network signer-free Hyperliquid /info client interface.

Review-only seam for a future authenticated *read-only* collector. The injected
transport is supplied exclusively by isolated tests; it is NOT a trusted
network channel, and this module is never imported by live bot workflows.
It cannot open an HTTP connection, acquire credentials, build an Exchange,
release a fence, approve an order, or prove where data came from.

Even a correctly parsed mock snapshot is HOLD. Never mistake the returned
legacy-compatible data shape for an account/position ownership attestation.
"""
from dataclasses import dataclass, field
import json
import re
from decimal import Decimal

from sender_review.signer_free_account_view_offline import (
    extract_signer_free_account_view_offline,
)

_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z", re.ASCII)
_MAX_JSON_BYTES = 131072
_TESTNET = "testnet"
# The only scope represented by PR #41's offline six-frame fixture.
# NOT an approved operational or live account. Runtime account pinning
# requires independent approval and an authenticated server-side policy.
_FIXTURE_ACCOUNT = "0x" + "1" * 40


@dataclass(frozen=True)
class UnwiredSignerFreeReadOnlyView:
    state: str = "HOLD"
    reason: str = "untrusted offline input; no authenticated account reader"
    equity: float | None = None
    positions: dict = field(default_factory=dict)
    observed_read_types: tuple[str, ...] = ()
    fixture_parsed: bool = False
    additional_spot_read_needed: bool = False
    exchange_origin_authenticated: bool = False
    account_scope_verified: bool = False
    snapshot_freshness_verified: bool = False
    account_wide_history_verified: bool = False
    position_ownership_verified: bool = False
    trading_key_available: bool = False
    order_authorized: bool = False
    close_authorized: bool = False
    leverage_authorized: bool = False


def _unique_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(_):
    raise ValueError("invalid JSON constant")


def _strict_document(raw):
    # A future collector must independently enforce origin, TLS and response
    # bounds BEFORE passing bytes into this non-authorizing parser.
    if type(raw) is not bytes or not 0 < len(raw) <= _MAX_JSON_BYTES:
        raise ValueError("missing or oversized fixture response")
    doc = json.loads(
        raw.decode("utf-8"), object_pairs_hook=_unique_json_pairs,
        parse_constant=_reject_json_constant,
    )
    if type(doc) is not dict:
        raise ValueError("expected object")
    return doc


# PR #41's disabled collector requires both total and hold for EVERY spot
# balance and checks hold <= total. The legacy strategy shape uses only the
# USDC total; checking only that field could hide inconsistent other balances.
# This remains purely a caller-supplied fixture check, not authenticated data.
_SPOT_COIN = re.compile(r"[A-Za-z0-9@._:/-]{1,64}\Z", re.ASCII)
_MAX_SPOT_BALANCES = 512
_SPOT_VALUE_LIMIT = Decimal("1000000000000")


def _validate_untrusted_spot_balances(document):
    if type(document) is not dict:
        raise ValueError("invalid spot fixture")
    rows = document.get("balances")
    if type(rows) is not list or len(rows) > _MAX_SPOT_BALANCES:
        raise ValueError("missing or oversized spot balances")
    seen = set()
    for row in rows:
        if type(row) is not dict:
            raise ValueError("invalid spot balance")
        coin = row.get("coin")
        if (type(coin) is not str or _SPOT_COIN.fullmatch(coin) is None
                or coin in seen):
            raise ValueError("invalid or duplicate spot coin")
        seen.add(coin)
        values = []
        for name in ("total", "hold"):
            raw = row.get(name)
            if (type(raw) is not str or not 0 < len(raw) <= 64
                    or raw.strip() != raw):
                raise ValueError("missing or invalid spot decimal")
            try:
                amount = Decimal(raw)
            except (ValueError, ArithmeticError):
                raise ValueError("invalid spot decimal") from None
            if (not amount.is_finite()
                    or not 0 <= amount <= _SPOT_VALUE_LIMIT):
                raise ValueError("invalid spot amount")
            values.append(amount)
        if values[1] > values[0]:
            raise ValueError("held spot amount exceeds total")
    return document


def inspect_unwired_signer_free_account_view(
    *, account, network, test_transport=None,
):
    """Apply exactly two allowlisted read shapes to MOCK response bytes.

    The test_transport callback receives a fresh dictionary containing only
    the fixed /info read type and PR #41's synthetic test account. It is
    never obtained from environment, installed as a real Info client, or
    permitted to send orders. A caller-provided callback cannot attest a
    network source; use only offline fakes until independent host approval.
    """
    hold = UnwiredSignerFreeReadOnlyView()
    if (type(account) is not str or _ACCOUNT.fullmatch(account) is None
            or account != _FIXTURE_ACCOUNT
            or type(network) is not str or network != _TESTNET
            or not callable(test_transport)):
        return hold
    seen = []
    try:
        def read(read_type):
            if read_type not in ("clearinghouseState", "spotClearinghouseState"):
                raise ValueError("unsupported info read")
            seen.append(read_type)
            request = {"type": read_type, "user": account}
            if read_type == "clearinghouseState":
                # PR #41's exact /info request requires the empty perp DEX.
                # Do not substitute another DEX or infer it from user input.
                request["dex"] = ""
            return _strict_document(test_transport(request))

        user_state = read("clearinghouseState")
        view = extract_signer_free_account_view_offline(user_state=user_state)
        if view.additional_spot_read_needed:
            spot = _validate_untrusted_spot_balances(
                read("spotClearinghouseState"),
            )
            view = extract_signer_free_account_view_offline(
                user_state=user_state, spot_user_state=spot,
            )
        if not view.fixture_parsed:
            return UnwiredSignerFreeReadOnlyView(
                reason="invalid or incomplete untrusted info response",
                observed_read_types=tuple(seen),
                additional_spot_read_needed=view.additional_spot_read_needed,
            )
        return UnwiredSignerFreeReadOnlyView(
            state="PARSED_UNTRUSTED_INFO_FIXTURE_HOLD",
            reason="read-only legacy shape parsed; origin, freshness, history, "
                   "ownership and all execution rights remain unverified",
            equity=view.equity,
            positions=view.positions,
            observed_read_types=tuple(seen),
            fixture_parsed=True,
        )
    except Exception:
        # Fail closed on malformed bytes, transport errors and unexpected
        # fixture behavior. Never expose HTTP payloads or exception detail.
        return UnwiredSignerFreeReadOnlyView(
            reason="read-only fixture unavailable or invalid",
            observed_read_types=tuple(seen),
        )


# Public market references used by all three original strategy executors:
# get_mid_price / coin_is_listed call all_mids(); get_size_decimals calls
# meta(). A future *trusted* collector needs independently enforced TLS,
# freshness, network/dex scoping and audit, not caller-supplied test_transport.
_MARKET_COIN = re.compile(r"[A-Z][A-Z0-9]{0,23}\Z", re.ASCII)
_PRICE_STRING = re.compile(r"(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,30})?\Z", re.ASCII)
_MAX_MARKET_COINS = 16
_MAX_UNIVERSE = 4096


@dataclass(frozen=True)
class UnwiredSignerFreeMarketView:
    state: str = "HOLD"
    reason: str = "untrusted market reference fixture"
    mid_prices: dict = field(default_factory=dict)
    size_decimals: dict = field(default_factory=dict)
    observed_read_types: tuple[str, ...] = ()
    market_reference_parsed: bool = False
    exchange_origin_authenticated: bool = False
    market_freshness_verified: bool = False
    asset_constraints_verified: bool = False
    prices_authorized_for_orders: bool = False
    order_authorized: bool = False
    leverage_authorized: bool = False
    signing_enabled: bool = False


def inspect_unwired_market_reference_view(
    *, coins, network, test_transport=None,
):
    """Parse synthetic perpetual allMids + meta, always return HOLD.

    Request envelopes specify only the first perp dex and are supplied to an
    offline fake callback. The parsed output never authorizes sizing, leverage
    updates, opening or closing orders. Unlike the original helper, an unknown
    coin's szDecimals is NOT silently defaulted to 3.
    """
    hold = UnwiredSignerFreeMarketView()
    if (
        type(network) is not str or network != _TESTNET
        or type(coins) is not tuple or not 0 < len(coins) <= _MAX_MARKET_COINS
        or any(type(c) is not str or _MARKET_COIN.fullmatch(c) is None
               for c in coins)
        or len(set(coins)) != len(coins)
        or not callable(test_transport)
    ):
        return hold
    seen = []
    try:
        def market_read(read_type):
            if read_type not in ("allMids", "meta"):
                raise ValueError("unsupported market reference read")
            seen.append(read_type)
            return _strict_document(test_transport({
                "type": read_type, "dex": "",
            }))

        mids_doc = market_read("allMids")
        prices = {}
        for coin in coins:
            raw = mids_doc.get(coin)
            if type(raw) is not str or _PRICE_STRING.fullmatch(raw) is None:
                raise ValueError("missing or invalid mid price")
            price = Decimal(raw)
            if not price.is_finite() or not 0 < price <= Decimal("1e12"):
                raise ValueError("invalid mid price range")
            prices[coin] = raw

        meta = market_read("meta")
        universe = meta.get("universe")
        if type(universe) is not list or len(universe) > _MAX_UNIVERSE:
            raise ValueError("invalid perp universe")
        sizes = {}
        requested = set(coins)
        for asset in universe:
            if type(asset) is not dict:
                raise ValueError("invalid perp asset")
            coin = asset.get("name")
            if coin not in requested:
                continue
            decimals = asset.get("szDecimals")
            if (
                coin in sizes
                or type(decimals) is not int or not 0 <= decimals <= 8
                or asset.get("isDelisted") is True
            ):
                raise ValueError("duplicate, invalid or delisted perp asset")
            sizes[coin] = decimals
        if set(sizes) != requested:
            raise ValueError("missing perp precision metadata")

        return UnwiredSignerFreeMarketView(
            state="PARSED_UNTRUSTED_MARKET_FIXTURE_HOLD",
            reason="synthetic market reference shape parsed; no verified "
                   "origin, freshness, asset constraints or trading authority",
            mid_prices=prices, size_decimals=sizes,
            observed_read_types=tuple(seen),
            market_reference_parsed=True,
        )
    except Exception:
        # Never expose response details, callback exception or input price.
        return UnwiredSignerFreeMarketView(
            reason="market reference fixture unavailable or invalid",
            observed_read_types=tuple(seen),
        )
