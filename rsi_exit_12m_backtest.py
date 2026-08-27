"""
rsi_exit_12m_backtest.py — 12-month rolling RSI exit research for Intraday 1h.

RESEARCH ONLY. This file does not import or call any live executor and cannot
place trades. It reproduces the live Intraday strategy rules using 1-hour
historical Yahoo market data because Hyperliquid only exposes the most recent
5,000 candles (~208 days at 1h), which is not enough for a 12-month test.

Compares:
  BASELINE  - current oscillator/ATR exit logic
  RSI 50/50 - after oscillator FLAT, long exits RSI<50; short exits RSI>50
  RSI 45/55 - after oscillator FLAT, long exits RSI<45; short exits RSI>55

ATR stops always remain immediate. Fees are included on entries/exits.
The year is also split into four equal rolling periods to test consistency.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
import yfinance as yf

from backtester import get_asset_profile
from indicators import average_true_range, butterworth_lowpass, two_pole_oscillator


RSI_PERIOD = 14
BW_CUTOFF = 0.1
SMA_PERIOD = 20
OSC_UPPER = 0.5
OSC_LOWER = -0.5
ATR_PERIOD = 14
ATR_STOP_MULT = 2.0
FEE_RATE = float(os.environ.get("BACKTEST_FEE_RATE", "0.00045"))
WARMUP_DAYS = 35
TEST_DAYS = 365

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


def fetch_yahoo_1h(ticker: str) -> pd.DataFrame:
    """Fetch ~400 days of 1h OHLCV with retry/backoff."""
    today = dt.datetime.now(dt.UTC)
    start = today - dt.timedelta(days=TEST_DAYS + WARMUP_DAYS + 3)
    end = today + dt.timedelta(days=1)

    last_error = None
    for attempt in range(3):
        try:
            df = yf.download(
                ticker,
                start=start.date().isoformat(),
                end=end.date().isoformat(),
                interval="1h",
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if not df.empty:
                break
        except Exception as exc:
            last_error = exc
        time.sleep(2 ** attempt)
    else:
        raise RuntimeError(f"Yahoo 1h fetch failed for {ticker}: {last_error}")

    needed = ["Open", "High", "Low", "Close", "Volume"]
    df = df[needed].dropna().copy()

    # Normalize timestamps to UTC-naive, matching the rest of the project.
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    df.index = idx
    df.index.name = "Date"

    # Use closed candles only. Anything in the current UTC hour is discarded.
    current_hour = pd.Timestamp.now(tz="UTC").floor("h").tz_localize(None)
    df = df[df.index < current_hour]
    return df.sort_index()


def rsi_wilder(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """Strictly causal Wilder RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
    rsi.name = "RSI"
    return rsi


def prepare_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Reproduce the live Intraday 1h indicator calculations."""
    out = df.copy()
    out["BW_Filter"] = butterworth_lowpass(out["Close"], cutoff=BW_CUTOFF)

    osc_raw = two_pole_oscillator(
        out["Close"],
        cutoff=BW_CUTOFF,
        sma_period=SMA_PERIOD,
    )
    osc_mean = osc_raw.rolling(100, min_periods=20).mean()
    osc_std = osc_raw.rolling(100, min_periods=20).std()
    out["TwoPole_Osc"] = ((osc_raw - osc_mean) / osc_std.replace(0, np.nan)).fillna(0.0)

    out["ATR"] = average_true_range(
        out["High"], out["Low"], out["Close"], period=ATR_PERIOD
    )
    out["RSI"] = rsi_wilder(out["Close"])
    return out


def _trade_return(side: int, entry: float, exit_: float) -> float:
    return exit_ / entry - 1.0 if side == 1 else entry / exit_ - 1.0


def simulate(
    df: pd.DataFrame,
    allow_short: bool,
    long_rsi_exit: float | None,
    short_rsi_exit: float | None,
) -> tuple[pd.Series, list[Trade]]:
    """Run baseline or RSI-gated exit logic on already prepared 1h data."""
    idx = df.index
    close = df["Close"].to_numpy(dtype=float)
    osc = df["TwoPole_Osc"].to_numpy(dtype=float)
    atr = df["ATR"].to_numpy(dtype=float)
    rsi = df["RSI"].to_numpy(dtype=float)

    n = len(df)
    position = np.zeros(n, dtype=int)
    fee_events = np.zeros(n, dtype=float)
    trades: list[Trade] = []

    side = 0
    entry_price = np.nan
    entry_i = -1
    peak_return = 0.0
    pending_flat = False

    for i in range(1, n):
        price = close[i]
        prev_osc = osc[i - 1]
        curr_osc = osc[i]
        atr_now = atr[i] if not np.isnan(atr[i]) else 0.0
        rsi_now = rsi[i]

        if side != 0:
            peak_return = max(
                peak_return,
                _trade_return(side, entry_price, price),
            )

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

        oscillator_exit = (
            (side == 1 and prev_osc > 0 >= curr_osc)
            or (side == -1 and prev_osc < 0 <= curr_osc)
        )
        if oscillator_exit:
            pending_flat = True

        # If oscillator momentum recovers before RSI confirms, keep holding.
        if pending_flat:
            if side == 1 and curr_osc > 0:
                pending_flat = False
            elif side == -1 and curr_osc < 0:
                pending_flat = False

        gated_exit = False
        gated_reason = ""
        if pending_flat and not np.isnan(rsi_now):
            if side == 1 and (long_rsi_exit is None or rsi_now < long_rsi_exit):
                gated_exit = True
                gated_reason = (
                    "oscillator exit"
                    if long_rsi_exit is None
                    else f"flat + RSI<{long_rsi_exit:g}"
                )
            elif side == -1 and (short_rsi_exit is None or rsi_now > short_rsi_exit):
                gated_exit = True
                gated_reason = (
                    "oscillator exit"
                    if short_rsi_exit is None
                    else f"flat + RSI>{short_rsi_exit:g}"
                )

        if side != 0 and (hard_exit or gated_exit):
            gross = _trade_return(side, entry_price, price)
            net = gross - (2.0 * FEE_RATE)
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
                    exit_reason=hard_reason if hard_exit else gated_reason,
                    bars_held=i - entry_i,
                )
            )
            fee_events[i] += FEE_RATE  # exit fee
            side = 0
            entry_price = np.nan
            entry_i = -1
            peak_return = 0.0
            pending_flat = False

        if side != 0:
            position[i] = side
            continue

        # Entries exactly match the live Intraday strategy.
        if np.isnan(prev_osc) or np.isnan(curr_osc):
            continue

        if prev_osc <= OSC_LOWER < curr_osc:
            side = 1
            entry_price = price
            entry_i = i
            peak_return = 0.0
            pending_flat = False
            position[i] = 1
            fee_events[i] += FEE_RATE
            continue

        if allow_short and prev_osc >= OSC_UPPER > curr_osc:
            side = -1
            entry_price = price
            entry_i = i
            peak_return = 0.0
            pending_flat = False
            position[i] = -1
            fee_events[i] += FEE_RATE

    pos_s = pd.Series(position, index=idx, dtype=float)
    gross_returns = pos_s.shift(1).fillna(0.0) * df["Close"].pct_change().fillna(0.0)
    net_returns = gross_returns - pd.Series(fee_events, index=idx)
    return net_returns, trades


def metrics(returns: pd.Series, trades: list[Trade]) -> dict:
    if returns.empty:
        return {}
    equity = (1.0 + returns).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)
    dd = equity / equity.cummax() - 1.0

    wins = [t for t in trades if t.net_return > 0]
    losses = [t for t in trades if t.net_return <= 0]
    return {
        "return_pct": total_return * 100.0,
        "max_dd_pct": float(dd.min()) * 100.0,
        "trades": len(trades),
        "win_rate_pct": len(wins) / len(trades) * 100.0 if trades else 0.0,
        "avg_win_pct": np.mean([t.net_return for t in wins]) * 100.0 if wins else 0.0,
        "avg_loss_pct": np.mean([t.net_return for t in losses]) * 100.0 if losses else 0.0,
        "avg_giveback_pct": np.mean([t.giveback for t in trades]) * 100.0 if trades else 0.0,
        "avg_bars": np.mean([t.bars_held for t in trades]) if trades else 0.0,
    }


def period_boundaries(index: pd.DatetimeIndex) -> list[tuple[str, pd.Timestamp, pd.Timestamp]]:
    start = index.min()
    end = index.max() + pd.Timedelta(hours=1)
    span = end - start
    boundaries = [start + span * i / 4 for i in range(5)]
    return [
        (f"P{i + 1}", boundaries[i], boundaries[i + 1])
        for i in range(4)
    ]


def run_asset(ticker: str) -> tuple[list[dict], list[dict]]:
    raw = fetch_yahoo_1h(ticker)
    if raw.empty or len(raw) < 1000:
        print(f"Skipping {ticker}: insufficient 1h history ({len(raw)} bars)")
        return [], []

    prepared = prepare_indicators(raw)
    test_end = prepared.index.max() + pd.Timedelta(hours=1)
    test_start = test_end - pd.Timedelta(days=TEST_DAYS)
    df = prepared[prepared.index >= test_start].copy()

    if len(df) < 5000:
        print(f"WARNING {ticker}: only {len(df)} bars in 12-month slice")

    profile = get_asset_profile(ticker)
    allow_short = bool(profile["allow_short"])
    variants = [
        ("BASELINE", None, None),
        ("RSI 50/50", 50.0, 50.0),
        ("RSI 45/55", 45.0, 55.0),
    ]

    annual_rows: list[dict] = []
    rolling_rows: list[dict] = []
    periods = period_boundaries(df.index)

    for name, long_exit, short_exit in variants:
        returns, trades = simulate(
            df,
            allow_short=allow_short,
            long_rsi_exit=long_exit,
            short_rsi_exit=short_exit,
        )
        annual = metrics(returns, trades)
        annual_rows.append({
            "asset": ticker,
            "variant": name,
            "bars": len(df),
            "shorts_allowed": allow_short,
            **annual,
        })

        for period_name, start, end in periods:
            period_returns = returns[(returns.index >= start) & (returns.index < end)]
            period_trades = [t for t in trades if start <= t.exit_time < end]
            pm = metrics(period_returns, period_trades)
            rolling_rows.append({
                "asset": ticker,
                "variant": name,
                "period": period_name,
                "start": start,
                "end": end,
                **pm,
            })

    print(
        f"{ticker}: {len(df)} closed 1h bars "
        f"[{df.index.min()} -> {df.index.max()}]"
    )
    return annual_rows, rolling_rows


def main() -> None:
    requested = os.environ.get("RSI_ASSETS", "").strip()
    assets = (
        [a.strip() for a in requested.split(",") if a.strip()]
        if requested
        else DEFAULT_ASSETS
    )

    print("=" * 88)
    print("12-MONTH RSI FLAT-EXIT RESEARCH — INTRADAY 1H")
    print("Data: Yahoo 1h history | Live bot: UNCHANGED | Orders: NONE")
    print(f"Fee assumption: {FEE_RATE * 100:.4f}% per side")
    print("Four rolling periods are reported to test robustness.")
    print("=" * 88)

    annual_rows: list[dict] = []
    rolling_rows: list[dict] = []

    for ticker in assets:
        try:
            annual, rolling = run_asset(ticker)
            annual_rows.extend(annual)
            rolling_rows.extend(rolling)
        except Exception as exc:
            print(f"ERROR {ticker}: {exc}")

    if not annual_rows:
        raise RuntimeError("No 12-month RSI results were produced")

    annual = pd.DataFrame(annual_rows)
    rolling = pd.DataFrame(rolling_rows)

    cols = [
        "asset", "variant", "return_pct", "max_dd_pct", "trades",
        "win_rate_pct", "avg_win_pct", "avg_loss_pct",
        "avg_giveback_pct", "avg_bars",
    ]
    print("\nFULL 12-MONTH PER-ASSET RESULTS")
    print(annual[cols].to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    summary = (
        annual.groupby("variant", as_index=False)
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
    print("\nFULL 12-MONTH COMBINED COMPARISON")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    print("\nROLLING 3-MONTH-LIKE PERIOD RETURNS BY ASSET")
    pivot = rolling.pivot_table(
        index=["asset", "period"],
        columns="variant",
        values="return_pct",
        aggfunc="first",
    ).reset_index()
    print(pivot.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    # Count how often each RSI rule beats the baseline across asset-periods.
    if {"BASELINE", "RSI 50/50", "RSI 45/55"}.issubset(pivot.columns):
        valid = pivot.dropna(subset=["BASELINE", "RSI 50/50", "RSI 45/55"]).copy()
        wins_5050 = int((valid["RSI 50/50"] > valid["BASELINE"]).sum())
        wins_4555 = int((valid["RSI 45/55"] > valid["BASELINE"]).sum())
        total = len(valid)
        print("\nROBUSTNESS VS BASELINE")
        print(f"RSI 50/50 beat baseline in {wins_5050}/{total} asset-periods")
        print(f"RSI 45/55 beat baseline in {wins_4555}/{total} asset-periods")

        by_asset = []
        for asset, group in valid.groupby("asset"):
            by_asset.append({
                "asset": asset,
                "periods": len(group),
                "rsi_5050_wins": int((group["RSI 50/50"] > group["BASELINE"]).sum()),
                "rsi_4555_wins": int((group["RSI 45/55"] > group["BASELINE"]).sum()),
            })
        print("\nCONSISTENCY BY ASSET")
        print(pd.DataFrame(by_asset).to_string(index=False))

    print("\nResearch only — no live strategy change has been made.")
    print("A live change should require improvement across multiple periods, not just")
    print("a higher single backtest return, while keeping drawdown/losses acceptable.")


if __name__ == "__main__":
    main()
