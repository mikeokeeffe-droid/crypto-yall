"""Live profit protection for the Aggressive bot only.

Keeps the existing signal exits unchanged and gives them precedence.

Two live protection layers are applied on entry-notional return:
1) Small-profit floor: once peak return reaches +1.00%, close if the current
   return falls to +0.25% or lower.
2) Existing trailing protection: once peak reaches +0.50%, close after a
   2.00 percentage-point giveback from the tracked peak.

After any protection exit, same-setup re-entry is blocked until the signal
resets or flips.
"""

import os

import aggressive_executor as aggressive
from intraday_data_loader import HL_SYMBOL_MAP
from reentry_lock import block_locked_entries, mark_pending_lock, refresh_locks

def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else float(default)


ARM_PCT = _env_float("AGGRESSIVE_PROFIT_ARM_PCT", 0.5)
GIVEBACK_PCT = _env_float("AGGRESSIVE_PROFIT_GIVEBACK_PCT", 2.0)
LOW_LEV_ARM_PCT = _env_float("AGGRESSIVE_LOW_LEV_PROTECTION", 0.5)
LOW_LEV_GIVEBACK_PCT = _env_float("AGGRESSIVE_LOW_LEV_GIVEBACK", 2.0)
HIGH_LEV_ARM_PCT = _env_float("AGGRESSIVE_HIGH_LEV_PROTECTION", 0.4)
HIGH_LEV_GIVEBACK_PCT = _env_float("AGGRESSIVE_HIGH_LEV_GIVEBACK", 1.0)
HIGH_LEV_THRESHOLD = _env_float("AGGRESSIVE_HIGH_LEV_THRESHOLD", 3.0)
SMALL_PROFIT_PEAK_PCT = float(os.environ.get("AGGRESSIVE_SMALL_PROFIT_PEAK_PCT", "1.0"))
SMALL_PROFIT_FLOOR_PCT = float(os.environ.get("AGGRESSIVE_SMALL_PROFIT_FLOOR_PCT", "0.25"))
ENABLED = os.environ.get("AGGRESSIVE_PROFIT_PROTECTION", "ON").upper() == "ON"

_peak_returns = {}
_state = None
_original_update_peak_tracking = aggressive.update_peak_tracking
_original_decide_trades = aggressive.decide_trades
_original_send_telegram = aggressive._send_telegram


def update_peak_tracking(state, positions, owned_coins):
    global _state
    _original_update_peak_tracking(state, positions, owned_coins)
    _state = state
    _peak_returns.clear()
    _peak_returns.update({str(k): float(v) for k, v in (state.get("peak_return_pct", {}) or {}).items()})


def _current_return_pct(position):
    entry_px = float(position.get("entry_px", 0.0) or 0.0)
    size = abs(float(position.get("size", 0.0) or 0.0))
    unrealized = float(position.get("unrealized_pnl", 0.0) or 0.0)
    notional = entry_px * size
    return unrealized / notional * 100.0 if notional > 0 else None


def decide_trades(signals, open_positions, max_positions, pyramid_state):
    trades = _original_decide_trades(signals, open_positions, max_positions, pyramid_state)
    if not ENABLED or _state is None:
        return trades

    locks = refresh_locks(_state, signals, HL_SYMBOL_MAP, open_positions)
    trades = block_locked_entries(trades, locks)
    already_closing = {t["hl_coin"] for t in trades if t.get("action") == "close"}
    ticker_by_coin = {coin: ticker for ticker, coin in HL_SYMBOL_MAP.items()}

    for coin, position in open_positions.items():
        if coin in already_closing:
            continue

        peak_pct = float(_peak_returns.get(coin, 0.0) or 0.0)
        current_pct = _current_return_pct(position)
        if current_pct is None:
            continue

        leverage = float(position.get("leverage", 1.0) or 1.0)
        is_high_leverage = leverage >= HIGH_LEV_THRESHOLD
        active_arm_pct = HIGH_LEV_ARM_PCT if is_high_leverage else LOW_LEV_ARM_PCT
        active_giveback_pct = (
            HIGH_LEV_GIVEBACK_PCT if is_high_leverage else LOW_LEV_GIVEBACK_PCT
        )
        protection_band = "HIGH LEVERAGE" if is_high_leverage else "LOW LEVERAGE"

        giveback = peak_pct - current_pct
        small_profit_trigger = (
            peak_pct >= SMALL_PROFIT_PEAK_PCT
            and current_pct <= SMALL_PROFIT_FLOOR_PCT
        )
        trailing_trigger = (
            peak_pct >= active_arm_pct
            and giveback >= active_giveback_pct
        )

        if not small_profit_trigger and not trailing_trigger:
            continue

        ticker = ticker_by_coin.get(coin)
        if ticker is None:
            continue
        side = "long" if float(position.get("size", 0.0)) > 0 else "short"

        if small_profit_trigger:
            protection_mode = "SMALL PROFIT FLOOR"
            reason = (
                f"small-profit protection: peak {peak_pct:.2f}% -> current {current_pct:.2f}% "
                f"(floor +{SMALL_PROFIT_FLOOR_PCT:.2f}% after peak +{SMALL_PROFIT_PEAK_PCT:.2f}%)"
            )
        else:
            protection_mode = f"{protection_band} TRAILING PROFIT PROTECTION"
            reason = (
                f"profit protection: {protection_band.lower()} {leverage:.0f}x | "
                f"peak {peak_pct:.2f}% -> current {current_pct:.2f}% "
                f"({giveback:.2f}pp giveback; armed at {active_arm_pct:.2f}%, "
                f"max {active_giveback_pct:.2f}pp)"
            )

        trades = [t for t in trades if t.get("hl_coin") != coin]
        trades.append({
            "ticker": ticker, "hl_coin": coin, "action": "close", "side": side,
            "exit_type": "PROFIT PROTECTION",
            "protection_mode": protection_mode,
            "protection_arm_pct": active_arm_pct,
            "protection_max_giveback_pct": active_giveback_pct,
            "position_leverage": leverage,
            "protection_band": protection_band,
            "protection_peak_pct": peak_pct,
            "protection_trigger_return_pct": current_pct,
            "protection_giveback_pct": giveback,
            "small_profit_peak_pct": SMALL_PROFIT_PEAK_PCT,
            "small_profit_floor_pct": SMALL_PROFIT_FLOOR_PCT,
            "reason": reason,
        })
        mark_pending_lock(_state, coin, side)
        already_closing.add(coin)
    return trades


def send_telegram(results, status_summary):
    enriched = []
    for result in results:
        item = dict(result)
        if item.get("action") == "close":
            reason = str(item.get("reason", ""))
            is_protection = reason.startswith("profit protection:") or reason.startswith("small-profit protection:")
            item.setdefault("exit_type", "PROFIT PROTECTION" if is_protection else "SIGNAL EXIT")
            diagnostics = [f"Exit type: {item['exit_type']}"]
            if "peak_return_pct" in item:
                diagnostics.append(f"Peak return: {float(item.get('peak_return_pct', 0.0) or 0.0):+.2f}%")
            if "realized_return_pct" in item:
                diagnostics.append(f"Net return: {float(item.get('realized_return_pct', 0.0) or 0.0):+.2f}%")
            if is_protection:
                if item.get("protection_mode"):
                    diagnostics.append(f"Protection mode: {item['protection_mode']}")
                diagnostics.append(
                    f"Small-profit floor: peak +{SMALL_PROFIT_PEAK_PCT:.2f}% / floor +{SMALL_PROFIT_FLOOR_PCT:.2f}%"
                )
                if item.get("position_leverage") is not None:
                    diagnostics.append(
                        f"Leverage band: {item.get('protection_band', 'UNKNOWN')} "
                        f"({float(item['position_leverage']):.0f}x)"
                    )
                diagnostics.append(
                    f"Trailing rule used: arm +{float(item.get('protection_arm_pct', ARM_PCT)):.2f}% "
                    f"/ max {float(item.get('protection_max_giveback_pct', GIVEBACK_PCT)):.2f}pp giveback"
                )
                diagnostics.append("Re-entry: locked until signal reset")
            item["reason"] = reason + " | " + " | ".join(diagnostics)
        enriched.append(item)
    _original_send_telegram(enriched, status_summary)


aggressive.update_peak_tracking = update_peak_tracking
aggressive.decide_trades = decide_trades
aggressive._send_telegram = send_telegram

if __name__ == "__main__":
    print(
        f"Aggressive live profit protection: {'ON' if ENABLED else 'OFF'} | "
        f"small-profit peak +{SMALL_PROFIT_PEAK_PCT:.2f}% -> floor +{SMALL_PROFIT_FLOOR_PCT:.2f}% | "
        f"low-lev arm +{LOW_LEV_ARM_PCT:.2f}% / {LOW_LEV_GIVEBACK_PCT:.2f}pp | "
        f"high-lev ({HIGH_LEV_THRESHOLD:.0f}x+) arm +{HIGH_LEV_ARM_PCT:.2f}% / "
        f"{HIGH_LEV_GIVEBACK_PCT:.2f}pp | re-entry lock ON"
    )
    aggressive.main()
