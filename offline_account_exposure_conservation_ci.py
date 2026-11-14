"""CI-only net-exposure conservation review across three bots.

Even an exact synthetic match is NOT exchange-authenticated provenance and
NEVER authorizes a protective close. Multiple bots share one Hyperliquid net
position: a journal/order assertion cannot prove any bot's exclusive share.
This deliberately conservative first-pass review HOLDS on manual, opposing,
partial-history, stale, malformed, replayed or unmatched synthetic evidence.

No Hyperliquid SDK, signing keys, network, order APIs or database mutations.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z", re.ASCII)
_COIN = re.compile(r"[A-Z][A-Z0-9]{0,23}\Z", re.ASCII)
_CLOID = re.compile(r"0x[0-9a-f]{32}\Z", re.ASCII)
_AMOUNT = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z", re.ASCII)
_BOTS = frozenset(("daily", "intraday", "aggressive"))
_FILL_FIELDS = frozenset((
    "origin", "fill_id", "bot", "order_id", "cloid", "account",
    "environment", "coin", "side", "size", "timestamp_ms",
))
_SNAPSHOT_FIELDS = frozenset((
    "origin", "account", "environment", "coin", "signed_size",
    "as_of_ms",
))


@dataclass(frozen=True)
class OfflineExposureConservationReview:
    state: str = "hold"
    reason: str = "independent position ownership unverified"
    structurally_consistent: bool = False
    ownership_verified: bool = False
    close_authorized: bool = False
    executable_close_size: None = None


def _number(raw, *, positive):
    if type(raw) is not str or _AMOUNT.fullmatch(raw) is None:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or (positive and value <= 0):
        return None
    if abs(value) > Decimal("1000000000"):
        return None
    return value


def review_synthetic_account_exposure_offline(
    *, account, environment, coin, initial_flat, complete_history,
    fills, position_snapshot,
):
    """Check algebraic conservation only. Returns HOLD in EVERY case.

    `complete_history=True` here is merely a CI-fixture assertion, NOT
    independent proof of exchange coverage. A sender may NOT consume this
    result as owned quantity, reduce-only approval or submit permission.
    """
    def hold(reason, consistent=False):
        return OfflineExposureConservationReview(
            reason=reason, structurally_consistent=consistent,
        )

    if (type(account) is not str or _ACCOUNT.fullmatch(account) is None
            or environment not in ("mainnet", "testnet")
            or type(coin) is not str or _COIN.fullmatch(coin) is None
            or initial_flat is not True or complete_history is not True
            or type(fills) is not list or not 1 <= len(fills) <= 256
            or type(position_snapshot) is not dict
            or set(position_snapshot) != _SNAPSHOT_FIELDS
            or position_snapshot["origin"] != "fixture"
            or position_snapshot["account"] != account
            or position_snapshot["environment"] != environment
            or position_snapshot["coin"] != coin
            or type(position_snapshot["as_of_ms"]) is not int
            or position_snapshot["as_of_ms"] <= 0):
        return hold("missing flat-start, complete-history or scoped fixture")

    observed = _number(position_snapshot["signed_size"], positive=False)
    if observed is None:
        return hold("invalid current net position")
    total = Decimal(0)
    previous_ts = 0
    seen_fills = set()
    order_identity = {}
    cloid_identity = {}
    directions = set()
    bot_set = set()

    for fill in fills:
        if type(fill) is not dict or set(fill) != _FILL_FIELDS:
            return hold("invalid synthetic fill schema")
        if (fill["origin"] != "fixture"
                or fill["account"] != account
                or fill["environment"] != environment
                or fill["coin"] != coin
                or type(fill["bot"]) is not str
                or fill["bot"] not in _BOTS):
            return hold("manual, foreign or unauthenticated activity")
        if (type(fill["fill_id"]) is not str
                or not 0 < len(fill["fill_id"]) <= 100
                or fill["fill_id"] in seen_fills
                or type(fill["order_id"]) is not int
                or fill["order_id"] <= 0
                or type(fill["cloid"]) is not str
                or _CLOID.fullmatch(fill["cloid"]) is None
                or fill["side"] not in ("buy", "sell")
                or type(fill["timestamp_ms"]) is not int
                or fill["timestamp_ms"] < previous_ts
                or fill["timestamp_ms"] > position_snapshot["as_of_ms"]):
            return hold("duplicate, stale, out-of-order or malformed fill")
        size = _number(fill["size"], positive=True)
        if size is None:
            return hold("invalid or unbounded fill size")
        identity = (fill["bot"], fill["side"], fill["cloid"])
        order_id = fill["order_id"]
        if order_id in order_identity and order_identity[order_id] != identity:
            return hold("one order has conflicting bot, side or CLOID")
        identity_by_cloid = (fill["bot"], fill["side"], order_id)
        if (fill["cloid"] in cloid_identity
                and cloid_identity[fill["cloid"]] != identity_by_cloid):
            return hold("CLOID reused for a different order or bot")
        order_identity[order_id] = identity
        cloid_identity[fill["cloid"]] = identity_by_cloid
        seen_fills.add(fill["fill_id"])
        previous_ts = fill["timestamp_ms"]
        directions.add(fill["side"])
        bot_set.add(fill["bot"])
        total += size if fill["side"] == "buy" else -size

    # Multiple directions include closes, cross-bot offsetting, and flips.
    # Such shared-account netting cannot be attributed using a naive sum.
    if len(directions) != 1:
        return hold("opposing trades or closes require independent reconciliation")
    if total != observed:
        return hold("synthetic fill total does not equal account net position")

    return hold(
        "synthetic conservation aligns for "
        + str(len(bot_set))
        + " bot(s); origin and exclusive ownership remain unverified",
        consistent=True,
    )
