"""P3 synthetic shared-account netting arithmetic — HOLD ONLY.

NO real exchange provenance, account credentials, network, signer, DB, trust
adapters, trading, automatic recovery, or fence release. Even when every
number matches, attributed fills are caller-supplied fiction for this test.
The results are diagnostic labels, never authority to close, retry, or resume.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

_BOTS = frozenset(("daily", "intraday", "aggressive"))
_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z")
_COIN = re.compile(r"[A-Z][A-Z0-9]{0,23}\Z")
_ID = re.compile(r"0x[0-9a-f]{32}\Z")
_QTY = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?\Z")


@dataclass(frozen=True)
class SyntheticAccountPosition:
    account: str
    coin: str
    before_signed: str  # positive long; negative short; untrusted
    after_signed: str


@dataclass(frozen=True)
class SyntheticBotAllocation:
    bot: str
    account: str
    coin: str
    before_signed: str
    after_signed: str


@dataclass(frozen=True)
class SyntheticFill:
    fill_id: str
    bot: str
    account: str
    coin: str
    cloid: str
    signed_delta: str  # buy positive; sell negative; UNVERIFIED


@dataclass(frozen=True)
class SyntheticNettingReview:
    state: str = "HOLD"
    reason: str = "missing-trusted-provenance"
    diagnostic: str = "untrusted-arithmetic-only; no execution permitted"
    synthetic_arithmetic_consistent: bool = False
    trusted_exchange_position: bool = False
    trusted_fill_history: bool = False
    bot_ownership_verified: bool = False
    account_lock_verified: bool = False
    retry_authorized: bool = False
    protective_close_authorized: bool = False
    fence_release_authorized: bool = False
    submit_authorized: bool = False
    signing_enabled: bool = False


def _parse_signed(value):
    if type(value) is not str or len(value) > 32 or _QTY.fullmatch(value) is None:
        return None
    try:
        result = Decimal(value)
    except (ValueError, InvalidOperation):
        return None
    if not result.is_finite() or abs(result) > Decimal("1000000"):
        return None
    return result


def review_synthetic_account_netting_offline(
    *, exchange: SyntheticAccountPosition, bots: tuple[SyntheticBotAllocation, ...],
    fills: tuple[SyntheticFill, ...], expected_account: str, expected_coin: str,
) -> SyntheticNettingReview:
    """Check synthetic before + attributed signed fills == after.

    This function cannot establish completeness, genuine bot attribution,
    real exchange positions, or whether an order was sent, filled or canceled.
    A numerical match MUST remain HOLD and MUST NOT be used to release a fence.
    """
    def hold(reason):
        return SyntheticNettingReview(reason=reason)

    if (
        type(exchange) is not SyntheticAccountPosition
        or type(bots) is not tuple or type(fills) is not tuple
        or type(expected_account) is not str
        or _ACCOUNT.fullmatch(expected_account) is None
        or type(expected_coin) is not str
        or _COIN.fullmatch(expected_coin) is None
        or exchange.account != expected_account or exchange.coin != expected_coin
    ):
        return hold("invalid-exchange-or-account-fixture")

    before = _parse_signed(exchange.before_signed)
    after = _parse_signed(exchange.after_signed)
    if before is None or after is None:
        return hold("invalid-exchange-quantity")

    if len(bots) != 3 or any(type(item) is not SyntheticBotAllocation for item in bots):
        return hold("missing-or-unattributable-bot")
    if frozenset(item.bot for item in bots) != _BOTS:
        return hold("missing-or-duplicate-bot")

    quantities = {}
    for item in bots:
        if item.account != expected_account or item.coin != expected_coin:
            return hold("cross-account-or-coin-attribution")
        b = _parse_signed(item.before_signed)
        a = _parse_signed(item.after_signed)
        if b is None or a is None:
            return hold("invalid-bot-quantity")
        quantities[item.bot] = (b, a)

    # An empty or partial collection cannot prove the exchange had no fills.
    # Even a nonempty, internally matching collection is NOT an authoritative
    # or complete fill history; no trusted source or pagination exists here.
    if not fills:
        return hold("missing-fill-provenance")
    if any(type(item) is not SyntheticFill for item in fills):
        return hold("invalid-fill-fixture")

    ids = set()
    per_bot = {bot: Decimal(0) for bot in _BOTS}
    for item in fills:
        if (
            type(item.fill_id) is not str or _ID.fullmatch(item.fill_id) is None
            or type(item.cloid) is not str or _ID.fullmatch(item.cloid) is None
            or item.fill_id in ids or item.bot not in _BOTS
            or item.account != expected_account or item.coin != expected_coin
        ):
            return hold("unverified-or-duplicate-fill-provenance")
        delta = _parse_signed(item.signed_delta)
        if delta is None or delta == 0:
            return hold("invalid-fill-quantity")
        ids.add(item.fill_id)
        per_bot[item.bot] += delta

    if sum((b for b, _ in quantities.values()), Decimal(0)) != before:
        return hold("exchange-before-not-attributed")
    for bot, (b, a) in quantities.items():
        if b + per_bot[bot] != a:
            return hold("bot-fill-arithmetic-mismatch")
    if before + sum(per_bot.values(), Decimal(0)) != after:
        return hold("exchange-fill-arithmetic-mismatch")
    if sum((a for _, a in quantities.values()), Decimal(0)) != after:
        return hold("exchange-after-not-attributed")

    # Even an arithmetic match is ambiguous if different bots claim opposing
    # exposure or opposing fills in a single netted shared-account market.
    # Zero exchange net exposure can conceal substantial open bot positions.
    directions = [
        item for b, a in quantities.values() for item in (b, a) if item != 0
    ] + [v for v in per_bot.values() if v != 0]
    if any(v > 0 for v in directions) and any(v < 0 for v in directions):
        return hold("shared-coin-offsetting-claims-unattributable")

    return SyntheticNettingReview(
        reason="synthetic-figures-match-but-exchange-provenance-unverified",
        synthetic_arithmetic_consistent=True,
    )
