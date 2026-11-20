"""Signer-free profit-protection TRIGGER comparison: strictly offline and HOLD.

Reproduces the sample-trigger and action-dictionary rules of the existing
Intraday/Aggressive profit-protection wrappers for reviewer parity tests.
It does NOT implement re-entry lock refresh/expiry, persistent state, full
entry decisions, exchange history, signed identity, reduce-only exits,
account ownership or real monitoring. Matching a fixture never authorizes
an order or proves that any existing position is protected.

There are NO network, environment, database, wallet, SDK, clock or signer
imports; do not import into current executors or deploy.
"""
from dataclasses import dataclass
import math

from sender_review.signer_free_account_view_offline import SignerFreeAccountView
from sender_review.pure_strategy_decisions_offline import TICKER_TO_COIN

COIN_TO_TICKER = {coin: ticker for ticker, coin in TICKER_TO_COIN.items()}


@dataclass(frozen=True)
class SyntheticProtectionRules:
    intraday_arm: float = 0.5
    intraday_giveback: float = 2.0
    aggressive_low_arm: float = 0.5
    aggressive_low_giveback: float = 2.0
    aggressive_high_arm: float = 0.4
    aggressive_high_giveback: float = 1.0
    aggressive_high_threshold: float = 3.0
    small_profit_peak: float = 1.0
    small_profit_floor: float = 0.25
    loss_cap_usd: float = 0.0


@dataclass(frozen=True)
class OfflineProtectionDecision:
    state: str = "HOLD"
    reason: str = "no trusted exchange origin or position ownership"
    local_trigger_reviewable: bool = False
    proposals: tuple[dict, ...] = ()
    proposed_lock_marks: tuple[tuple[str, str], ...] = ()
    exchange_origin_authenticated: bool = False
    account_scope_verified: bool = False
    position_ownership_verified: bool = False
    existing_position_protected: bool = False
    reentry_locks_persisted: bool = False
    effective_reduce_only_verified: bool = False
    runtime_identity_authenticated: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def _number(value, *, positive=False):
    if type(value) not in (int, float):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(result) or abs(result) > 1_000_000_000_000:
        return None
    if positive and result <= 0:
        return None
    return result


def _valid_inputs(bot, account_view, peak_returns, initial_actions,
                  protection_only, enabled, rules):
    if (type(bot) is not str or bot not in ("intraday", "aggressive")
            or type(account_view) is not SignerFreeAccountView
            or account_view.state != "PARSED_READONLY_FIXTURE_HOLD"
            or account_view.fixture_parsed is not True
            or type(peak_returns) is not dict or len(peak_returns) > 256
            or type(initial_actions) not in (list, tuple)
            or len(initial_actions) > 256
            or type(protection_only) is not bool or type(enabled) is not bool
            or type(rules) is not SyntheticProtectionRules):
        return False
    for key, value in vars(rules).items():
        if _number(value) is None or value < 0:
            return False
    if rules.aggressive_high_threshold <= 0:
        return False
    for coin, peak in peak_returns.items():
        if (type(coin) is not str or coin not in COIN_TO_TICKER
                or _number(peak) is None):
            return False
    for coin, pos in account_view.positions.items():
        if type(coin) is not str or coin not in COIN_TO_TICKER or type(pos) is not dict:
            return False
        if (_number(pos.get("size")) in (None, 0)
                or _number(pos.get("entry_px"), positive=True) is None
                or _number(pos.get("unrealized_pnl")) is None
                or _number(pos.get("leverage"), positive=True) is None):
            return False
    for action in initial_actions:
        if (type(action) is not dict
                or type(action.get("hl_coin")) is not str
                or action["hl_coin"] not in COIN_TO_TICKER
                or action.get("action") not in (
                    "open_long", "open_short", "pyramid_long",
                    "pyramid_short", "close")
                or type(action.get("side")) is not str
                or action["side"] not in ("long", "short")):
            return False
    return True


def inspect_pure_profit_protection_offline(
    *, bot, account_view, peak_returns, initial_actions=(),
    protection_only=False, enabled=True, rules=SyntheticProtectionRules(),
):
    """Compare only the legacy trigger layer on synthetic, untrusted data.

    The caller's synthetic snapshot and peaks are NOT independently checked.
    The original wrappers' refresh_locks(), block_locked_entries() and
    mark_pending_lock() are deliberately absent; persistence, lock handling
    and trusted time are separate mandatory cutover gates.
    """
    denied = OfflineProtectionDecision()
    if not _valid_inputs(bot, account_view, peak_returns, initial_actions,
                         protection_only, enabled, rules):
        return denied
    actions = [] if protection_only else [dict(x) for x in initial_actions]
    if not enabled:
        return OfflineProtectionDecision(
            state="DISABLED_PROTECTION_FIXTURE_HOLD",
            reason="protection switched off in synthetic fixture; no safe exit",
            local_trigger_reviewable=True, proposals=tuple(actions),
        )
    closes = {a["hl_coin"] for a in actions if a["action"] == "close"}
    pending = []
    for coin, pos in account_view.positions.items():
        if coin in closes:
            continue
        size = abs(float(pos["size"]))
        entry_px = float(pos["entry_px"])
        pnl = float(pos["unrealized_pnl"])
        leverage = float(pos["leverage"])
        try:
            current_pct = pnl / (entry_px * size) * 100
        except (OverflowError, ZeroDivisionError):
            return denied
        if not math.isfinite(current_pct):
            return denied
        stored_peak = float(peak_returns.get(coin, 0.0) or 0.0)
        # Intraday wrapper maxes current with stored; Aggressive's
        # update_peak_tracking sets the stored peak before its decision run.
        peak = max(stored_peak, current_pct) if bot == "intraday" else stored_peak
        giveback = peak - current_pct
        high = (bot == "aggressive"
                and leverage >= rules.aggressive_high_threshold)
        if bot == "intraday":
            arm = rules.intraday_arm
            max_giveback = rules.intraday_giveback
        elif high:
            arm = rules.aggressive_high_arm
            max_giveback = rules.aggressive_high_giveback
        else:
            arm = rules.aggressive_low_arm
            max_giveback = rules.aggressive_low_giveback
        hit_loss = rules.loss_cap_usd > 0 and pnl <= -rules.loss_cap_usd
        hit_floor = (peak >= rules.small_profit_peak
                     and current_pct <= rules.small_profit_floor)
        hit_trail = peak >= arm and giveback >= max_giveback
        if not (hit_loss or hit_floor or hit_trail):
            continue

        side = "long" if pos["size"] > 0 else "short"
        band = "HIGH LEVERAGE" if high else "LOW LEVERAGE"
        if hit_loss:
            mode = "USD LOSS CAP"
            reason = (f"loss cap: sampled unrealized P&L ${pnl:+.4f} "
                      f"reached -${rules.loss_cap_usd:.2f}; "
                      "actual realized loss may be larger after fees/slippage")
        elif hit_floor:
            mode = "SMALL PROFIT FLOOR"
            if bot == "intraday":
                reason = (
                    f"small-profit protection: peak {peak:+.2f}% -> current {current_pct:+.2f}% "
                    f"(floor +{rules.small_profit_floor:.2f}% after peak +{rules.small_profit_peak:.2f}%)"
                )
            else:
                reason = (
                    f"small-profit protection: peak {peak:.2f}% -> current {current_pct:.2f}% "
                    f"(floor +{rules.small_profit_floor:.2f}% after peak +{rules.small_profit_peak:.2f}%)"
                )
        else:
            mode = ("TRAILING PROFIT PROTECTION" if bot == "intraday"
                    else f"{band} TRAILING PROFIT PROTECTION")
            if bot == "intraday":
                reason = (f"profit protection: peak {peak:+.2f}% -> current {current_pct:+.2f}% "
                          f"({giveback:.2f}pp giveback; armed at {arm:.2f}%)")
            else:
                reason = (f"profit protection: {band.lower()} {leverage:.0f}x | "
                          f"peak {peak:.2f}% -> current {current_pct:.2f}% "
                          f"({giveback:.2f}pp giveback; armed at {arm:.2f}%, "
                          f"max {max_giveback:.2f}pp)")
        result = {
            "ticker": COIN_TO_TICKER[coin], "hl_coin": coin,
            "action": "close", "side": side, "close_size": size,
            "reason": reason,
            "exit_type": "LOSS PROTECTION" if hit_loss else "PROFIT PROTECTION",
            "protection_mode": mode, "protection_arm_pct": arm,
            "protection_peak_pct": peak, "protection_trigger_return_pct": current_pct,
            "protection_giveback_pct": giveback,
            "small_profit_peak_pct": rules.small_profit_peak,
            "small_profit_floor_pct": rules.small_profit_floor,
        }
        if bot == "aggressive":
            result.update({
                "protection_max_giveback_pct": max_giveback,
                "position_leverage": leverage, "protection_band": band,
            })
        actions = [a for a in actions if a["hl_coin"] != coin]
        actions.append(result)
        closes.add(coin)
        pending.append((coin, side))
    return OfflineProtectionDecision(
        state="PURE_TRIGGER_FIXTURE_HOLD",
        reason="pure local trigger comparison only; reentry lock and real exit unverified",
        local_trigger_reviewable=True,
        proposals=tuple(actions),
        proposed_lock_marks=tuple(pending),
    )
