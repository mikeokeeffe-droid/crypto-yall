"""Live profit protection for the Aggressive bot only.

Arms after peak return reaches +0.5% on entry notional. Once armed, closes
when current return has fallen 2.0 percentage points from the tracked peak.
The existing aggressive signal exits remain unchanged and take precedence.
After a protection exit, same-setup re-entry is blocked until the signal resets.
"""

import os

import aggressive_executor as aggressive
from intraday_data_loader import HL_SYMBOL_MAP
from reentry_lock import block_locked_entries, mark_pending_lock, refresh_locks

ARM_PCT = float(os.environ.get("AGGRESSIVE_PROFIT_ARM_PCT", "0.5"))
GIVEBACK_PCT = float(os.environ.get("AGGRESSIVE_PROFIT_GIVEBACK_PCT", "2.0"))
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
        if peak_pct < ARM_PCT:
            continue
        current_pct = _current_return_pct(position)
        if current_pct is None:
            continue
        giveback = peak_pct - current_pct
        if giveback < GIVEBACK_PCT:
            continue
        ticker = ticker_by_coin.get(coin)
        if ticker is None:
            continue
        side = "long" if float(position.get("size", 0.0)) > 0 else "short"
        trades = [t for t in trades if t.get("hl_coin") != coin]
        trades.append({
            "ticker": ticker, "hl_coin": coin, "action": "close", "side": side,
            "exit_type": "PROFIT PROTECTION", "protection_arm_pct": ARM_PCT,
            "protection_peak_pct": peak_pct, "protection_trigger_return_pct": current_pct,
            "protection_giveback_pct": giveback,
            "reason": f"profit protection: peak {peak_pct:.2f}% -> current {current_pct:.2f}% ({giveback:.2f}pp giveback; armed at {ARM_PCT:.2f}%)",
        })
        mark_pending_lock(_state, coin, side)
        already_closing.add(coin)
    return trades


def send_telegram(results, status_summary):
    enriched = []
    for result in results:
        item = dict(result)
        if item.get("action") == "close":
            item.setdefault("exit_type", "PROFIT PROTECTION" if str(item.get("reason", "")).startswith("profit protection:") else "SIGNAL EXIT")
            diagnostics = [f"Exit type: {item['exit_type']}"]
            if "peak_return_pct" in item:
                diagnostics.append(f"Peak return: {float(item.get('peak_return_pct', 0.0) or 0.0):+.2f}%")
            if "realized_return_pct" in item:
                diagnostics.append(f"Net return: {float(item.get('realized_return_pct', 0.0) or 0.0):+.2f}%")
            if "protection_giveback_pct" in item:
                diagnostics.append(f"Protection giveback: {float(item.get('protection_giveback_pct', 0.0) or 0.0):.2f}pp")
                diagnostics.append(f"Protection rule: arm +{float(item.get('protection_arm_pct', ARM_PCT)):.2f}% / max {GIVEBACK_PCT:.2f}pp giveback")
                diagnostics.append("Re-entry: locked until signal reset")
            item["reason"] = item.get("reason", "") + " | " + " | ".join(diagnostics)
        enriched.append(item)
    _original_send_telegram(enriched, status_summary)


aggressive.update_peak_tracking = update_peak_tracking
aggressive.decide_trades = decide_trades
aggressive._send_telegram = send_telegram

if __name__ == "__main__":
    print(f"Aggressive live profit protection: {'ON' if ENABLED else 'OFF'} | arm +{ARM_PCT:.2f}% | max giveback {GIVEBACK_PCT:.2f}pp | re-entry lock ON")
    aggressive.main()
