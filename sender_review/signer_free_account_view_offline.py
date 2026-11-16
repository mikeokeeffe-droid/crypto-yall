"""Pure signer-free account-view extraction for a future read-only strategy input.

This is useful parsing code but deliberately NOT a collector, a deployed
strategy worker, an exchange-origin verifier or an authenticated account
snapshot. It takes caller-supplied decoded /info documents; no private key,
network access, Info/Exchange SDK, database, signer or order path is present.
All results remain HOLD and cannot confer trading authority.

For well-formed sample values it preserves the legacy Daily/Intraday/
Aggressive get_open_positions and get_account_equity *data shapes*. It
deliberately refuses ambiguous input and cannot replace independently verified
account-wide ownership, complete history, precision or risk checks.
"""
from dataclasses import dataclass, field
import math
import re

_COIN = re.compile(r"[A-Z][A-Z0-9]{0,23}\Z", re.ASCII)
_MAX_POSITIONS = 256
_MAX_BALANCES = 512
_MAX_ABSOLUTE_SIZE = 1_000_000
_MAX_ABSOLUTE_VALUE = 1_000_000_000_000


@dataclass(frozen=True)
class SignerFreeAccountView:
    state: str = "HOLD"
    reason: str = "no authenticated read-only exchange origin"
    fixture_parsed: bool = False
    positions: dict = field(default_factory=dict)
    equity: float | None = None
    legacy_spot_fallback_used: bool = False
    additional_spot_read_needed: bool = False
    exchange_origin_authenticated: bool = False
    account_scope_verified: bool = False
    position_ownership_verified: bool = False
    historic_baseline_verified: bool = False
    snapshot_freshness_verified: bool = False
    signer_available: bool = False
    order_authorized: bool = False
    close_authorized: bool = False
    leverage_authorized: bool = False


def _finite_number(value, *, allow_negative=False):
    if type(value) not in (str, int, float) or (
        type(value) is str and not 0 < len(value) <= 64
    ):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    if (not math.isfinite(number)
            or abs(number) > _MAX_ABSOLUTE_VALUE
            or (not allow_negative and number < 0)):
        return None
    return number


def extract_signer_free_account_view_offline(*, user_state, spot_user_state=None):
    """Map supplied synthetic /info account docs to original worker data shape.

    The source bot's equity function consults *spot_user_state* whenever perp
    accountValue < 10. The agreed six-frame collector only reads perp state;
    therefore the missing spot document is a visible HOLD, not a guess.
    Spot fallback values are not account equity or an entry risk grant.
    """
    denied = SignerFreeAccountView()
    if type(user_state) is not dict:
        return denied
    margin = user_state.get("marginSummary")
    raw_positions = user_state.get("assetPositions")
    if (type(margin) is not dict or type(raw_positions) is not list
            or len(raw_positions) > _MAX_POSITIONS):
        return SignerFreeAccountView(reason="missing or oversized account document")
    equity = _finite_number(margin.get("accountValue"))
    if equity is None:
        return SignerFreeAccountView(reason="invalid account equity value")

    positions = {}
    seen_coins = set()
    for raw in raw_positions:
        if type(raw) is not dict or type(raw.get("position")) is not dict:
            return SignerFreeAccountView(reason="invalid position record")
        pos = raw["position"]
        coin = pos.get("coin")
        if (type(coin) is not str or _COIN.fullmatch(coin) is None
                or coin in seen_coins):
            return SignerFreeAccountView(reason="duplicate or invalid position coin")
        seen_coins.add(coin)
        size = _finite_number(pos.get("szi"), allow_negative=True)
        if size is None or abs(size) > _MAX_ABSOLUTE_SIZE:
            return SignerFreeAccountView(reason="invalid signed position size")
        if size == 0:
            # The original strategy helper filters flat position entries.
            continue
        entry_price = _finite_number(pos.get("entryPx"))
        unrealized = _finite_number(pos.get("unrealizedPnl"), allow_negative=True)
        raw_leverage = pos.get("leverage", 1.0)
        if type(raw_leverage) is dict:
            raw_leverage = raw_leverage.get("value", 1.0)
        # The original helper uses 'raw_leverage or 1.0'; valid zero/blank
        # legacy observations map to 1.0, but bad/nonfinite values now HOLD.
        if raw_leverage in (0, 0.0, "", None):
            raw_leverage = 1.0
        leverage = _finite_number(raw_leverage)
        if (entry_price is None or unrealized is None
                or leverage is None or leverage <= 0):
            return SignerFreeAccountView(reason="invalid position market fields")
        positions[coin] = {
            "size": size, "entry_px": entry_price,
            "unrealized_pnl": unrealized, "leverage": leverage,
        }

    used_spot = False
    if equity < 10:
        if spot_user_state is None:
            return SignerFreeAccountView(
                reason="legacy equity calculation requires an additional "
                       "spotUserState read; six-frame perp readset is insufficient",
                additional_spot_read_needed=True,
            )
        if (type(spot_user_state) is not dict
                or type(spot_user_state.get("balances")) is not list
                or len(spot_user_state["balances"]) > _MAX_BALANCES):
            return SignerFreeAccountView(reason="invalid spot account document")
        seen = set()
        for balance in spot_user_state["balances"]:
            if type(balance) is not dict or type(balance.get("coin")) is not str:
                return SignerFreeAccountView(reason="invalid spot balance")
            coin = balance["coin"]
            if coin in seen:
                return SignerFreeAccountView(reason="duplicate spot balance")
            seen.add(coin)
            if coin == "USDC":
                spot_total = _finite_number(balance.get("total", 0))
                if spot_total is None:
                    return SignerFreeAccountView(reason="invalid spot USDC balance")
                equity = spot_total
                used_spot = True

    return SignerFreeAccountView(
        state="PARSED_READONLY_FIXTURE_HOLD",
        reason="compatible strategy data shape only; no trusted origin, "
               "fence, ownership, trade or close permission",
        fixture_parsed=True, positions=positions, equity=equity,
        legacy_spot_fallback_used=used_spot,
    )
