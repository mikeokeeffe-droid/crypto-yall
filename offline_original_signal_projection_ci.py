"""CI-only projection of the three original bots' candidate entry dictionaries.

The originals produce additional strategy metadata (ticker/reason/rank).
Only a known, source-reviewed entry shape is converted into a strict
three-field request for the separate signer-free review adapter.
Unexpected or spoofed fields, closes and pyramids HOLD. This module never
authenticates a workload, authorizes orders or loads an exchange client.
"""
from dataclasses import dataclass
import json
import math

# Pinned from original HL_TICKER_MAP / HL_SYMBOL_MAP; drift needs review.
_TICKERS = {
    "BTC-USD": "BTC", "ETH-USD": "ETH", "SOL-USD": "SOL",
    "AVAX-USD": "AVAX", "LINK-USD": "LINK",
    "SUI20947-USD": "SUI", "XRP-USD": "XRP", "ONDO-USD": "ONDO",
}
_BOTS = frozenset(("daily", "intraday", "aggressive"))
_FIELDS_COMMON = frozenset(("ticker", "hl_coin", "action", "side", "reason"))
_REASONS = {
    "daily": {
        "open_long": frozenset(("BUY signal",)),
        "open_short": frozenset(("ENTER SHORT signal",)),
    },
    "intraday": {
        "open_long": frozenset(("buy signal", "sync to hold_long")),
        "open_short": frozenset(("enter_short signal", "sync to hold_short")),
    },
    "aggressive": {
        "open_long": frozenset(("buy signal", "sync to hold_long")),
        "open_short": frozenset(("enter_short signal", "sync to hold_short")),
    },
}


@dataclass(frozen=True)
class OfflineSignalProjection:
    state: str = "hold"
    trade_json: str | None = None
    reason: str = "unreviewed original candidate"
    submit_authorized: bool = False
    ownership_verified: bool = False


def project_original_entry_candidate_offline(*, verified_bot, candidate):
    """Return only exact action/side/hl_coin JSON; never trade permission.

    Reject rather than silently drop unknown metadata, even when its value
    is false. The original candidate's priority/confidence is not an
    approval or proof of exchange position ownership.
    """
    held = OfflineSignalProjection()
    if (type(verified_bot) is not str or verified_bot not in _BOTS
            or type(candidate) is not dict):
        return held
    score_key = "confidence" if verified_bot == "daily" else "priority"
    if set(candidate) != (_FIELDS_COMMON | {score_key}):
        return held
    action = candidate.get("action")
    side = candidate.get("side")
    ticker = candidate.get("ticker")
    coin = candidate.get("hl_coin")
    score = candidate.get(score_key)
    reason = candidate.get("reason")
    if (type(action) is not str
            or action not in ("open_long", "open_short")
            or side != ("long" if action == "open_long" else "short")
            or type(ticker) is not str
            or ticker not in _TICKERS or _TICKERS[ticker] != coin
            or type(reason) is not str
            or reason not in _REASONS[verified_bot][action]
            or type(score) not in (float, int)
            or not math.isfinite(score) or score < 0):
        return held
    trade = {"action": action, "side": side, "hl_coin": coin}
    return OfflineSignalProjection(
        state="projected_review_only",
        trade_json=json.dumps(trade, sort_keys=True, separators=(",", ":")),
        reason="original candidate metadata validated and discarded; no order",
    )
