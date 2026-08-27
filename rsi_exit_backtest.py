"""
rsi_exit_backtest.py — Research-only RSI confirmation test for Intraday FLAT exits.

This file is intentionally isolated from the live executors and strategies.
It does NOT place orders or change live bot behaviour.

It compares the current 1h Intraday exit logic against two RSI(14)
confirmation variants:

1. BASELINE
   - ATR stop exits immediately.
   - Long exits when the 2-pole oscillator crosses below zero.
   - Short exits when the oscillator crosses above zero.

2. RSI 50/50
   - ATR stop still exits immediately.
   - After an oscillator FLAT/exit event, a long only exits when RSI < 50.
   - After an oscillator FLAT/exit event, a short only exits when RSI > 50.

3. RSI 45/55
   - ATR stop still exits immediately.
   - Long exits when RSI < 45.
   - Short exits when RSI > 55.

The purpose is to test whether RSI reduces premature FLAT exits without
allowing losing trades to run excessively.

Fees:
The default market-order fee assumption is 0.045% per side (4.5 bps),
configurable via BACKTEST_FEE_RATE.

Examples:
    python rsi_exit_backtest.py
    BACKTEST_FEE_RATE=0.00045 python rsi_exit_backtest.py
    RSI_ASSETS=BTC-USD,ETH-USD python rsi_exit_backtest.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtester import get_asset_profile
from indicators import average_true_range, butterworth_lowpass, two_pole_oscillator
from intraday_data_loader import fetch_candles


RSI_PERIOD = 14
BW_CUTOFF = 0.1
SMA_PERIOD = 20
OSC_UPPER = 0.5
OSC_LOWER = -0.5
ATR_PERIOD = 14
ATR_STOP_MULT = 2.0
LOOKBACK_HOURS = int(os.environ.get("RSI_LOOKBACK_HOURS", "2000"))
FEE_RATE = float(os.environ.get("BACKTEST_FEE_RATE", "0.00045"))

DEFAULT_ASSETS = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "AVAX-USD",
    "LINK-USD",
    "SUI20947-USD",
    "XRP-USD",
    "ONDO-USD",
]


@dataclass
class Trade:
    side: int
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    gross_return: float
    net_return: float
    peak_return: float
    giveback: float
    exit_reason: str
    bars_held: int


def rsi_wilder(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """Strictly causal Wilder RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()
    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    # If there have been gains but no losses, RSI is 100.
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
    rsi.name = "RSI"
    return rsi


def prepare_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Reproduce the live Intraday strategy's indicator calculations."""
    out = df.copy()

    bw = butterworth_lowpass(out["Close"], cutoff=BW_CUTOFF)
    osc_raw = two_pole_oscillator(
        out["Close"],
        cutoff=BW_CUTOFF,
        sma_period=SMA_PERIOD,
    )
    atr = average_true_range(
        out["High"],
        out["Low"],
        out["Close"],
        period=ATR_PERIOD,
    )

    osc_mean = osc_raw.rolling(100, min_periods=20).mean()
    osc_std = osc_raw.rolling(100, min_periods=20).std()
    osc = (osc_raw - osc_mean) / osc_std.replace(0, np.nan)

    out["BW_Filter"] = bw
    out["TwoPole_Osc"] = osc.fillna(0.0)
    out["ATR"] = atr
    out["RSI"] = rsi_wilder(out["Close"])
    return out


def _trade_return(side: int, entry: float, exit_: float) -> float:
    if side == 1:
        return exit_ / entry - 1.0
    return entry / exit_ - 1.0


def simulate(
    df: pd.DataFrame,
    allow_short: bool,
    long_rsi_exit: float | None,
    short_rsi_exit: float | None,
) -> tuple[pd.Series, list[Trade], float]:
    """
    Simulate the live Intraday entry/ATR logic with an optional RSI gate only
    on oscillator-generated FLAT exits.

    ATR stops are never delayed by RSI.
    """
    idx = df.index
    close = df["Close"].to_numpy(dtype=float)
    osc = df["TwoPole_Osc"].to_numpy(dtype=float)
    atr = df["ATR"].to_numpy(dtype=float)
    rsi = df["RSI"].to_numpy(dtype=float)

    n = len(df)
    position = np.zeros(n, dtype=int)
    trades: list[Trade] = []

    side = 0
    entry_price = np.nan
    entry_i = -1
    peak_return = 0.0
    pending_flat = False
    fees_paid = 0.0

    for i in range(1, n):
        price = close[i]
        prev_osc = osc[i - 1]
        curr_osc = osc[i]
        atr_now = atr[i] if not np.isnan(atr[i]) else 0.0
        rsi_now = rsi[i]

        if side != 0:
            current_ret = _trade_return(side, entry_price, price)
            peak_return = max(peak_return, current_ret)

        # Hard ATR stop always wins; RSI is never allowed to override risk.
        hard_exit = False
        hard_reason = ""
        if side == 1 and not np.isnan(entry_price):
            stop = entry_price - ATR_STOP_MULT * atr_now
            if atr_now > 0 and price <= stop:
                hard_exit = True
                hard_reason = "ATR stop"
        elif side == -1 and not np.isnan(entry_price):
            stop = entry_price + ATR_STOP_MULT * atr_now
            if atr_now > 0 and price >= stop:
                hard_exit = True
                hard_reason = "ATR stop"

        oscillator_exit = False
        if side == 1 and prev_osc > 0 >= curr_osc:
            oscillator_exit = True
        elif side == -1 and prev_osc < 0 <= curr_osc:
            oscillator_exit = True

        if oscillator_exit:
            pending_flat = True

        # If momentum clearly recovers while we delayed a FLAT exit, cancel
        # the pending state and continue the existing position.
        if pending_flat:
            if side == 1 and curr_osc > 0:
                pending_flat = False
            elif side == -1 and curr_osc < 0:
                pending_flat = False

        rsi_exit = False
        rsi_reason = ""
        if pending_flat and not np.isnan(rsi_now):
            if side == 1:
                if long_rsi_exit is None or rsi_now < long_rsi_exit:
                    rsi_exit = True
                    rsi_reason = (
                        "oscillator exit"
                        if long_rsi_exit is None
                        else f"flat + RSI<{long_rsi_exit:g}"
                    )
            elif side == -1:
                if short_rsi_exit is None or rsi_now > short_rsi_exit:
                    rsi_exit = True
                    rsi_reason = (
                        "oscillator exit"
                        if short_rsi_exit is None
                        else f"flat + RSI>{short_rsi_exit:g}"
                    )

        if side != 0 and (hard_exit or rsi_exit):
            gross = _trade_return(side, entry_price, price)
            # Market order entry + market order exit.
            trade_fees = 2.0 * FEE_RATE
            net = gross - trade_fees
            fees_paid += trade_fees

            trades.append(
                Trade(
                    side=side,
                    entry_time=idx[entry_i],
                    exit_time=idx[i],
                    entry_price=float(entry_price),
                    exit_price=float(price),
                    gross_return=float(gross),
                    net_return=float(net),
                    peak_return=float(peak_return),
                    giveback=float(peak_return - net),
                    exit_reason=hard_reason if hard_exit else rsi_reason,
                    bars_held=i - entry_i,
                )
            )

            side = 0
            entry_price = np.nan
            entry_i = -1
            peak_return = 0.0
            pending_flat = False

        # Keep the position state for this closed candle.
        if side != 0:
            position[i] = side
            continue

        # Entry rules are exactly the live Intraday strategy rules.
        if np.isnan(prev_osc) or np.isnan(curr_osc):
            continue

        if prev_osc <= OSC_LOWER < curr_osc:
            side = 1
            entry_price = price
            entry_i = i
            peak_return = 0.0
            pending_flat = False
            position[i] = 1
            continue

        if allow_short and prev_osc >= OSC_UPPER > curr_osc:
            side = -1
            entry_price = price
            entry_i = i
            peak_return = 0.0
            pending_flat = False
            position[i] = -1

    # Mark-to-market an open final trade in the equity curve, but do not count
    # it as a completed trade statistic.
    pos_s = pd.Series(position, index=idx, dtype=float)
    returns = df["Close"].pct_change().fillna(0.0)
    strat = pos_s.shift(1).fillna(0.0) * returns

    # Subtract transaction fees from the strategy-return stream at each
    # completed entry/exit transition for an apples-to-apples equity curve.
    turnover = pos_s.diff().abs().fillna(pos_s.abs())
    fee_drag = turnover * FEE_RATE
    net_returns = strat - fee_drag

    return net_returns, trades, fees_paid


def metrics(returns: pd.Series, trades: list[Trade]) -> dict:
    equity = (1.0 + returns).cumprod()
    if equity.empty:
        return {}

    total_return = float(equity.iloc[-1] - 1.0)
    peak = equity.cummax()
    dd = equity / peak - 1.0
    max_dd = float(dd.min())

    wins = [t for t in trades if t.net_return > 0]
    losses = [t for t in trades if t.net_return <= 0]

    return {
        "return_pct": total_return * 100.0,
        "max_dd_pct": max_dd * 100.0,
        "trades": len(trades),
        "win_rate_pct": (
            len(wins) / len(trades) * 100.0
            if trades
            else 0.0
        ),
        "avg_win_pct": (
            np.mean([t.net_return for t in wins]) * 100.0
            if wins
            else 0.0
        ),
        "avg_loss_pct": (
            np.mean([t.net_return for t in losses]) * 100.0
            if losses
            else 0.0
        ),
        "avg_giveback_pct": (
            np.mean([t.giveback for t in trades]) * 100.0
            if trades
            else 0.0
        ),
        "avg_bars": (
            np.mean([t.bars_held for t in trades])
            if trades
            else 0.0
        ),
    }


def run_asset(ticker: str) -> list[dict]:
    raw = fetch_candles(
        ticker,
        interval="1h",
        lookback_hours=LOOKBACK_HOURS,
    )
    if raw.empty or len(raw) < 150:
        print(f"Skipping {ticker}: insufficient data ({len(raw)} bars)")
        return []

    df = prepare_indicators(raw)
    profile = get_asset_profile(ticker)
    allow_short = bool(profile["allow_short"])

    variants = [
        ("BASELINE", None, None),
        ("RSI 50/50", 50.0, 50.0),
        ("RSI 45/55", 45.0, 55.0),
    ]

    rows = []
    for name, long_exit, short_exit in variants:
        ret, trades, fees_paid = simulate(
            df,
            allow_short=allow_short,
            long_rsi_exit=long_exit,
            short_rsi_exit=short_exit,
        )
        m = metrics(ret, trades)
        if not m:
            continue
        rows.append(
            {
                "asset": ticker,
                "variant": name,
                "bars": len(df),
                "shorts_allowed": allow_short,
                **m,
                "completed_fee_drag_pct": fees_paid * 100.0,
            }
        )

    return rows


def main() -> None:
    requested = os.environ.get("RSI_ASSETS", "").strip()
    assets = (
        [a.strip() for a in requested.split(",") if a.strip()]
        if requested
        else DEFAULT_ASSETS
    )

    print("=" * 78)
    print("RSI FLAT-EXIT RESEARCH — INTRADAY 1H")
    print("LIVE BOT CODE IS NOT USED OR MODIFIED BY THIS TEST")
    print(f"Lookback: {LOOKBACK_HOURS} hours")
    print(f"Fee assumption: {FEE_RATE * 100:.4f}% per side")
    print("=" * 78)

    all_rows: list[dict] = []
    for ticker in assets:
        try:
            rows = run_asset(ticker)
            all_rows.extend(rows)
        except Exception as exc:
            print(f"ERROR {ticker}: {exc}")

    if not all_rows:
        raise RuntimeError("No RSI backtest results were produced")

    result = pd.DataFrame(all_rows)

    display_cols = [
        "asset",
        "variant",
        "return_pct",
        "max_dd_pct",
        "trades",
        "win_rate_pct",
        "avg_win_pct",
        "avg_loss_pct",
        "avg_giveback_pct",
        "avg_bars",
    ]

    print("\nPER-ASSET RESULTS")
    print(
        result[display_cols].to_string(
            index=False,
            float_format=lambda x: f"{x:,.3f}",
        )
    )

    summary = (
        result.groupby("variant", as_index=False)
        .agg(
            avg_return_pct=("return_pct", "mean"),
            median_return_pct=("return_pct", "median"),
            avg_max_dd_pct=("max_dd_pct", "mean"),
            total_trades=("trades", "sum"),
            avg_win_rate_pct=("win_rate_pct", "mean"),
            avg_giveback_pct=("avg_giveback_pct", "mean"),
            avg_bars=("avg_bars", "mean"),
        )
    )

    print("\nCOMBINED COMPARISON")
    print(
        summary.to_string(
            index=False,
            float_format=lambda x: f"{x:,.3f}",
        )
    )

    baseline = summary.loc[summary["variant"] == "BASELINE"]
    if not baseline.empty:
        base_ret = float(baseline.iloc[0]["avg_return_pct"])
        print("\nCHANGE VS BASELINE")
        for _, row in summary.iterrows():
            if row["variant"] == "BASELINE":
                continue
            delta = float(row["avg_return_pct"]) - base_ret
            print(
                f"{row['variant']}: average return change "
                f"{delta:+.3f} percentage points"
            )

    print("\nResearch only. Do not change the live bot from these numbers alone.")
    print("We should prefer a rule that improves returns/giveback without a")
    print("material increase in drawdown or average losing-trade size.")


if __name__ == "__main__":
    main()
