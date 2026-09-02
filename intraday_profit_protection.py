"""Live profit protection wrapper for the Intraday executor.

Keeps Intraday entry logic unchanged. Existing signal exits take precedence.
For an owned open position, profit protection arms once peak return on entry
notional reaches +0.50%. If the trade then gives back 2.00 percentage points
from its tracked peak, this wrapper replaces any non-close decision for that
coin with a close.

The peak and current return use the same entry-notional definition as the
Aggressive profit-protection implementation, not Hyperliquid leveraged ROE.
"""

from __future__ import annotations

import os

import intraday_executor as base

ARM_PCT = float(os.environ.get("INTRADAY_PROFIT_ARM_PCT", "0.5"))
GIVEBACK_PCT = float(os.environ.get("INTRADAY_PROFIT_GIVEBACK_PCT", "2.0"))
ENABLED = os.environ.get("INTRADAY_PROFIT_PROTECTION", "ON").upper() != "OFF"

_original_decide_trades = base.decide_trades
_original_send_telegram = base._send_telegram
_state: dict | None = None


def _protected_decide_trades(signals: dict, open_positions: dict, max_positions: int) -> list[dict]:
    trades = _original_decide_trades(signals, open_positions, max_positions)
    if not ENABLED or _state is None:
        return trades

    # Existing signal exits always win.
    signal_closes = {
        t["hl_coin"] for t in trades if t.get("action") == "close"
    }
    peak_returns = _state.get("peak_return_pct", {}) or {}
    ticker_by_coin = {
        coin: ticker for ticker, coin in base.HL_SYMBOL_MAP.items()
    }

    protection_closes: dict[str, dict] = {}
    for coin, pos in open_positions.items():
        if coin in signal_closes:
            continue
        entry_px = float(pos.get("entry_px", 0.0) or 0.0)
        size = abs(float(pos.get("size", 0.0) or 0.0))
        current_pnl = float(pos.get("unrealized_pnl", 0.0) or 0.0)
        if entry_px <= 0 or size <= 0:
            continue
        current_pct = current_pnl / (entry_px * size) * 100.0
        peak_pct = max(float(peak_returns.get(coin, 0.0) or 0.0), current_pct)
        if peak_pct < ARM_PCT:
            continue
        giveback = peak_pct - current_pct
        if giveback < GIVEBACK_PCT:
            continue
        ticker = ticker_by_coin.get(coin)
        if not ticker:
            print(f"Intraday profit protection skipped {coin}: ticker unavailable")
            continue
        protection_closes[coin] = {
            "ticker": ticker,
            "hl_coin": coin,
            "action": "close",
            "side": "long" if float(pos.get("size", 0.0)) > 0 else "short",
            "reason": (
                f"profit protection: peak {peak_pct:+.2f}% -> current {current_pct:+.2f}% "
                f"({giveback:.2f}pp giveback; armed at {ARM_PCT:.2f}%)"
            ),
            "exit_type": "PROFIT PROTECTION",
            "protection_arm_pct": ARM_PCT,
            "protection_peak_pct": peak_pct,
            "protection_trigger_return_pct": current_pct,
            "protection_giveback_pct": giveback,
        }

    if not protection_closes:
        return trades

    # Remove any open/sync decision for a protected coin and close instead.
    trades = [t for t in trades if t.get("hl_coin") not in protection_closes]
    trades.extend(protection_closes.values())
    return trades


def _telegram_with_exit_diagnostics(results: list[dict], summary: str) -> None:
    enriched = []
    for item in results:
        r = dict(item)
        if r.get("action") == "close":
            reason = str(r.get("reason", ""))
            is_protection = reason.startswith("profit protection:")
            exit_type = "PROFIT PROTECTION" if is_protection else "SIGNAL EXIT"
            details = [f"Exit type: {exit_type}"]
            if r.get("peak_return_pct") is not None:
                details.append(f"Peak return: {float(r['peak_return_pct']):+.2f}%")
            if r.get("realized_return_pct") is not None:
                details.append(f"Net return: {float(r['realized_return_pct']):+.2f}%")
            if is_protection:
                details.append(
                    f"Protection: arm +{ARM_PCT:.2f}% / max {GIVEBACK_PCT:.2f}pp giveback"
                )
            r["reason"] = reason + " | " + " | ".join(details)
        enriched.append(r)
    _original_send_telegram(enriched, summary)


def main() -> None:
    global _state
    original_load_state = base.load_state

    def load_and_capture() -> dict:
        global _state
        state = original_load_state()
        _state = state
        return state

    base.load_state = load_and_capture
    base.decide_trades = _protected_decide_trades
    base._send_telegram = _telegram_with_exit_diagnostics
    print(
        f"Intraday profit protection {'ON' if ENABLED else 'OFF'}: "
        f"arm +{ARM_PCT:.2f}%, max giveback {GIVEBACK_PCT:.2f}pp"
    )
    base.main()


if __name__ == "__main__":
    main()
