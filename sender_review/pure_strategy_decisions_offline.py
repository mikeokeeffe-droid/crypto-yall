"""Pure REVIEW-ONLY copies of three legacy decide_trades functions.

Unlike the existing executor modules, this has no signer, exchange SDK,
database, HTTP, wallet, environment reads, or executable order transport.
Only caller-provided SYNTHETIC account-view and signal fixtures are parsed.
The output preserves historical local decision ordering for comparison; it
does NOT include live bot ownership filters, USD risk, protection wrappers,
BTC/ETH dual-short gate, authenticated exchange account history or a
protected sender. It is NEVER permission to submit/close a real order.

Compare this logic with AST-isolated original functions in offline CI.
Changing rules requires independent risk review and explicit approval.
"""
from dataclasses import dataclass
import math

from sender_review.signer_free_account_view_offline import SignerFreeAccountView

TICKER_TO_COIN = {
    "BTC-USD": "BTC",
    "ETH-USD": "ETH",
    "SOL-USD": "SOL",
    "AVAX-USD": "AVAX",
    "LINK-USD": "LINK",
    "SUI20947-USD": "SUI",
    "XRP-USD": "XRP",
    "ONDO-USD": "ONDO",
}
_BOTS = frozenset(("daily", "intraday", "aggressive"))
_ACTIONS = frozenset((
    "buy", "enter_short", "hold_long", "hold_short", "sell_exit",
    "cover_short", "liquidate", "hold", "idle",
))


@dataclass(frozen=True)
class PureStrategyDecisionReview:
    state: str = "HOLD"
    reason: str = "untrusted offline strategy decision fixture"
    local_decisions_compared: bool = False
    proposed_actions: tuple[dict, ...] = ()
    # All external evidence and execution authority flags remain False.
    exchange_origin_authenticated: bool = False
    account_scope_verified: bool = False
    ownership_verified: bool = False
    live_signal_verified: bool = False
    market_risk_verified: bool = False
    protection_runner_verified: bool = False
    runtime_identity_authenticated: bool = False
    durable_fence_reserved: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def _number(value):
    if type(value) not in (int, float):
        return None
    x = float(value)
    return x if math.isfinite(x) and abs(x) <= 1_000_000 else None


def _inputs_valid(bot, signals, account_view, max_positions, pyramid_state):
    if (
        type(bot) is not str or bot not in _BOTS
        or type(signals) is not dict or len(signals) > len(TICKER_TO_COIN)
        or type(account_view) is not SignerFreeAccountView
        or account_view.state != "PARSED_READONLY_FIXTURE_HOLD"
        or account_view.fixture_parsed is not True
        or type(max_positions) is not int or not 0 <= max_positions <= 32
        or type(pyramid_state) is not dict
        or (bot != "aggressive" and pyramid_state)
    ):
        return False
    for ticker, sig in signals.items():
        if (type(ticker) is not str or ticker not in TICKER_TO_COIN
                or type(sig) is not dict or type(sig.get("action")) is not str
                or sig["action"] not in _ACTIONS):
            return False
        if (bot == "daily" and sig["action"] in ("buy", "enter_short")
                and _number(sig.get("bull_conf" if sig["action"] == "buy"
                                    else "bear_conf")) is None):
            return False
        if (bot != "daily" and sig["action"] in (
                "buy", "enter_short", "hold_long", "hold_short")
                and _number(sig.get("osc")) is None):
            return False
        if ("pyramid_added" in sig and type(sig["pyramid_added"]) is not bool):
            return False
    for coin, count in pyramid_state.items():
        if (type(coin) is not str or coin not in TICKER_TO_COIN.values()
                or type(count) is not int or not 0 <= count <= 2):
            return False
    for coin, pos in account_view.positions.items():
        if (type(coin) is not str or type(pos) is not dict
                or _number(pos.get("size")) in (None, 0)
                or _number(pos.get("unrealized_pnl")) is None):
            return False
    return True


def inspect_pure_strategy_decisions_offline(
    *, bot, signals, account_view, max_positions, pyramid_state=None,
):
    """Produce strictly inert proposals matching the three original decisions.

    Caller-supplied data is not trusted account or signal provenance; every
    output is permanently HOLD. This function MUST NOT drive a sender.
    """
    if pyramid_state is None:
        pyramid_state = {}
    if not _inputs_valid(bot, signals, account_view, max_positions, pyramid_state):
        return PureStrategyDecisionReview(reason="invalid synthetic strategy inputs")
    positions = account_view.positions
    trades = []

    # Close-pass behavior taken from each original decide_trades (NOT the
    # wrappers): Daily also handles liquidate; intraday/aggressive do not.
    for ticker, sig in signals.items():
        coin = TICKER_TO_COIN[ticker]
        pos = positions.get(coin)
        if pos is None:
            continue
        action = sig["action"]
        is_long, is_short = pos["size"] > 0, pos["size"] < 0
        reason = None
        if bot == "daily":
            if action == "sell_exit" and is_long:
                reason = "SELL / EXIT signal"
            elif action == "liquidate" and (is_long or is_short):
                reason = "LIQUIDATE TO CASH signal"
            elif action == "cover_short" and is_short:
                reason = "COVER SHORT signal"
            elif action == "buy" and is_short:
                reason = "Signal flipped long while short"
            elif action == "enter_short" and is_long:
                reason = "Signal flipped short while long"
        elif (
            (action == "sell_exit" and is_long)
            or (action == "cover_short" and is_short)
            or (action == "buy" and is_short)
            or (action == "enter_short" and is_long)
        ):
            reason = f"{action} signal"
        if reason is not None:
            trades.append({
                "ticker": ticker, "hl_coin": coin, "action": "close",
                "side": "long" if is_long else "short",
                "close_size": abs(float(pos.get("size", 0.0) or 0.0)),
                "reason": reason,
            })

    closes = {t["hl_coin"] for t in trades if t["action"] == "close"}
    remaining = {c: p for c, p in positions.items() if c not in closes}

    # Only the original Aggressive decide_trades allows pyramid adds.
    if bot == "aggressive":
        for ticker, sig in signals.items():
            coin = TICKER_TO_COIN[ticker]
            if coin not in remaining or not sig.get("pyramid_added"):
                continue
            pnl = float(remaining[coin].get("unrealized_pnl", 0.0) or 0.0)
            if pnl <= 0:
                continue
            count = pyramid_state.get(coin, 0)
            if count >= 2:
                continue
            side = "long" if remaining[coin]["size"] > 0 else "short"
            trades.append({
                "ticker": ticker, "hl_coin": coin,
                "action": f"pyramid_{side}", "side": side,
                "reason": f"pyramid add #{count + 1} (osc re-entry)",
            })

    slots = max(0, max_positions - len(remaining))
    candidates = []
    for ticker, sig in signals.items():
        coin = TICKER_TO_COIN[ticker]
        if coin in remaining:
            continue
        action = sig["action"]
        if bot == "daily":
            if action == "buy":
                candidates.append({
                    "ticker": ticker, "hl_coin": coin, "action": "open_long",
                    "side": "long", "reason": "BUY signal",
                    "confidence": sig["bull_conf"],
                })
            elif action == "enter_short":
                candidates.append({
                    "ticker": ticker, "hl_coin": coin, "action": "open_short",
                    "side": "short", "reason": "ENTER SHORT signal",
                    "confidence": sig["bear_conf"],
                })
        else:
            if action in ("buy", "hold_long"):
                candidates.append({
                    "ticker": ticker, "hl_coin": coin, "action": "open_long",
                    "side": "long", "reason": (
                        "buy signal" if action == "buy" else "sync to hold_long"
                    ), "priority": abs(sig["osc"]),
                })
            elif action in ("enter_short", "hold_short"):
                candidates.append({
                    "ticker": ticker, "hl_coin": coin, "action": "open_short",
                    "side": "short", "reason": (
                        "enter_short signal" if action == "enter_short"
                        else "sync to hold_short"
                    ), "priority": abs(sig["osc"]),
                })
    candidates.sort(key=lambda c: c[
        "confidence" if bot == "daily" else "priority"
    ], reverse=True)
    trades.extend(candidates[:slots])
    return PureStrategyDecisionReview(
        state="PURE_LOCAL_DECISIONS_FIXTURE_HOLD",
        reason="synthetic decisions only, NOT authenticated account, ownership,"
               " signal, protected exits, or submission authorisation",
        local_decisions_compared=True, proposed_actions=tuple(trades),
    )
