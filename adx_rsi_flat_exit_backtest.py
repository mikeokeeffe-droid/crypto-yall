"""
adx_rsi_flat_exit_backtest.py — ADX vs RSI FLAT-exit research for Intraday 1h.

RESEARCH ONLY. No live executor imports, no API keys, and no order placement.

Purpose:
  Compare the current Intraday oscillator exit against two confirmation ideas
  after an oscillator FLAT/zero-cross event:

  BASELINE   - exit immediately on oscillator zero-cross (current behaviour)
  RSI 45/55  - long waits for RSI<45; short waits for RSI>55
  ADX <25    - either side waits for trend strength to weaken below 25
  ADX <30    - either side waits for trend strength to weaken below 30

ATR stops always remain immediate. If the oscillator recovers before the
confirmation arrives, the pending FLAT exit is cancelled, matching the earlier
RSI research design.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import rsi_exit_12m_backtest as research

ADX_PERIOD = 14
FEE_RATE = 0.00045
WINDOW_DAYS = 60
STEP_DAYS = 30

ASSETS = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "AVAX-USD",
    "LINK-USD",
    "SUI20947-USD",
    "XRP-USD",
    "ONDO-USD",
]

VARIANTS = [
    ("BASELINE", "baseline", None),
    ("RSI 45/55", "rsi", None),
    ("ADX <25", "adx", 25.0),
    ("ADX <30", "adx", 30.0),
]


def adx_wilder(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.Series:
    """Strictly causal Wilder-style ADX using only current/past OHLC bars."""
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=df.index,
        dtype=float,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index,
        dtype=float,
    )

    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_smoothed = plus_dm.ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()
    minus_smoothed = minus_dm.ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()

    plus_di = 100.0 * plus_smoothed / atr.replace(0, np.nan)
    minus_di = 100.0 * minus_smoothed / atr.replace(0, np.nan)
    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum.replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    adx.name = "ADX"
    return adx


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = research.prepare_indicators(df)
    out["ADX"] = adx_wilder(out)
    return out


def trade_return(side: int, entry: float, exit_: float) -> float:
    return exit_ / entry - 1.0 if side == 1 else entry / exit_ - 1.0


def simulate(
    df: pd.DataFrame,
    allow_short: bool,
    mode: str,
    adx_threshold: float | None = None,
) -> tuple[pd.Series, list[research.Trade]]:
    idx = df.index
    close = df["Close"].to_numpy(dtype=float)
    osc = df["TwoPole_Osc"].to_numpy(dtype=float)
    atr = df["ATR"].to_numpy(dtype=float)
    rsi = df["RSI"].to_numpy(dtype=float)
    adx = df["ADX"].to_numpy(dtype=float)

    n = len(df)
    position = np.zeros(n, dtype=int)
    fee_events = np.zeros(n, dtype=float)
    trades: list[research.Trade] = []

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
        adx_now = adx[i]

        if side != 0:
            peak_return = max(peak_return, trade_return(side, entry_price, price))

        hard_exit = False
        hard_reason = ""
        if side == 1 and not np.isnan(entry_price):
            stop = entry_price - research.ATR_STOP_MULT * atr_now
            if atr_now > 0 and price <= stop:
                hard_exit = True
                hard_reason = "ATR stop"
        elif side == -1 and not np.isnan(entry_price):
            stop = entry_price + research.ATR_STOP_MULT * atr_now
            if atr_now > 0 and price >= stop:
                hard_exit = True
                hard_reason = "ATR stop"

        oscillator_exit = (
            (side == 1 and prev_osc > 0 >= curr_osc)
            or (side == -1 and prev_osc < 0 <= curr_osc)
        )
        if oscillator_exit:
            pending_flat = True

        # Cancel the pending exit if oscillator momentum recovers.
        if pending_flat:
            if side == 1 and curr_osc > 0:
                pending_flat = False
            elif side == -1 and curr_osc < 0:
                pending_flat = False

        confirmed_exit = False
        reason = ""
        if pending_flat:
            if mode == "baseline":
                confirmed_exit = True
                reason = "oscillator exit"
            elif mode == "rsi" and not np.isnan(rsi_now):
                if side == 1 and rsi_now < 45.0:
                    confirmed_exit = True
                    reason = "flat + RSI<45"
                elif side == -1 and rsi_now > 55.0:
                    confirmed_exit = True
                    reason = "flat + RSI>55"
            elif mode == "adx" and adx_threshold is not None and not np.isnan(adx_now):
                if adx_now < adx_threshold:
                    confirmed_exit = True
                    reason = f"flat + ADX<{adx_threshold:g}"

        if side != 0 and (hard_exit or confirmed_exit):
            gross = trade_return(side, entry_price, price)
            net = gross - (2.0 * FEE_RATE)
            trades.append(
                research.Trade(
                    side=side,
                    entry_time=idx[entry_i],
                    exit_time=idx[i],
                    entry_price=float(entry_price),
                    exit_price=float(price),
                    gross_return=float(gross),
                    net_return=float(net),
                    peak_return=float(peak_return),
                    giveback=float(peak_return - net),
                    exit_reason=hard_reason if hard_exit else reason,
                    bars_held=i - entry_i,
                )
            )
            fee_events[i] += FEE_RATE
            side = 0
            entry_price = np.nan
            entry_i = -1
            peak_return = 0.0
            pending_flat = False

        if side != 0:
            position[i] = side
            continue

        if np.isnan(prev_osc) or np.isnan(curr_osc):
            continue

        # Same entry rules as the live Intraday strategy.
        if prev_osc <= research.OSC_LOWER < curr_osc:
            side = 1
            entry_price = price
            entry_i = i
            peak_return = 0.0
            pending_flat = False
            position[i] = 1
            fee_events[i] += FEE_RATE
            continue

        if allow_short and prev_osc >= research.OSC_UPPER > curr_osc:
            side = -1
            entry_price = price
            entry_i = i
            peak_return = 0.0
            pending_flat = False
            position[i] = -1
            fee_events[i] += FEE_RATE

    pos_s = pd.Series(position, index=idx, dtype=float)
    gross_returns = (
        pos_s.shift(1).fillna(0.0) * df["Close"].pct_change().fillna(0.0)
    )
    net_returns = gross_returns - pd.Series(fee_events, index=idx)
    return net_returns, trades


def rolling_windows(index: pd.DatetimeIndex):
    start = index.min()
    final = index.max() + pd.Timedelta(hours=1)
    window = pd.Timedelta(days=WINDOW_DAYS)
    step = pd.Timedelta(days=STEP_DAYS)
    cursor = start
    number = 1
    while cursor + window <= final:
        yield f"W{number:02d}", cursor, cursor + window
        cursor += step
        number += 1


def main() -> None:
    print("=" * 104)
    print("ADX VS RSI FLAT-EXIT RESEARCH — INTRADAY 1H")
    print("Research only | Live bot unchanged | No orders")
    print(f"History: {research.TEST_DAYS} days | Fee: {FEE_RATE * 100:.4f}% per side")
    print("Rules: BASELINE vs RSI 45/55 vs ADX<25 vs ADX<30")
    print("=" * 104)

    annual_rows = []
    rolling_rows = []

    for ticker in ASSETS:
        try:
            raw = research.fetch_yahoo_1h(ticker)
            prepared = prepare(raw)
            test_end = prepared.index.max() + pd.Timedelta(hours=1)
            test_start = test_end - pd.Timedelta(days=research.TEST_DAYS)
            df = prepared[prepared.index >= test_start].copy()

            allow_short = bool(research.get_asset_profile(ticker)["allow_short"])
            print(
                f"\n{ticker}: {len(df)} bars "
                f"[{df.index.min()} -> {df.index.max()}]"
            )

            for name, mode, threshold in VARIANTS:
                returns, trades = simulate(df, allow_short, mode, threshold)
                m = research.metrics(returns, trades)
                annual_rows.append({"asset": ticker, "variant": name, **m})
                print(
                    f"  FULL {name:<10} return={m.get('return_pct', 0):+8.3f}% "
                    f"DD={m.get('max_dd_pct', 0):+8.3f}% "
                    f"trades={m.get('trades', 0):4d} "
                    f"win={m.get('win_rate_pct', 0):5.1f}% "
                    f"giveback={m.get('avg_giveback_pct', 0):6.3f}% "
                    f"bars={m.get('avg_bars', 0):5.1f}"
                )

                for window_name, start, end in rolling_windows(df.index):
                    wr = returns[(returns.index >= start) & (returns.index < end)]
                    wt = [t for t in trades if start <= t.exit_time < end]
                    wm = research.metrics(wr, wt)
                    rolling_rows.append(
                        {
                            "asset": ticker,
                            "window": window_name,
                            "variant": name,
                            **wm,
                        }
                    )
        except Exception as exc:
            print(f"ERROR {ticker}: {exc}")

    annual = pd.DataFrame(annual_rows)
    rolling = pd.DataFrame(rolling_rows)
    if annual.empty or rolling.empty:
        raise RuntimeError("No ADX/RSI research results were produced")

    print("\n" + "=" * 104)
    print("COMBINED FULL-YEAR SUMMARY — MEAN ACROSS ASSETS")
    print("=" * 104)
    for name, _, _ in VARIANTS:
        a = annual[annual.variant == name]
        print(
            f"{name:<10} avg_return={a.return_pct.mean():+8.3f}% "
            f"avg_DD={a.max_dd_pct.mean():+8.3f}% "
            f"trades={int(a.trades.sum()):4d} "
            f"avg_giveback={a.avg_giveback_pct.mean():6.3f}% "
            f"avg_bars={a.avg_bars.mean():5.1f}"
        )

    pivot = rolling.pivot_table(
        index=["asset", "window"],
        columns="variant",
        values="return_pct",
        aggfunc="first",
    ).dropna()

    print("\nROLLING 60-DAY ROBUSTNESS")
    for candidate in ["RSI 45/55", "ADX <25", "ADX <30"]:
        delta = pivot[candidate] - pivot["BASELINE"]
        wins = int((delta > 0).sum())
        total = len(delta)
        print(
            f"{candidate:<10} beats baseline {wins:3d}/{total:<3d} "
            f"({wins / total * 100:5.1f}%) | avg_delta={delta.mean():+6.3f}pp "
            f"median={delta.median():+6.3f}pp | worst={delta.min():+6.3f}pp"
        )

    print("\nASSET CONSISTENCY")
    for asset in ASSETS:
        p = pivot.loc[asset]
        print(f"\n{asset}")
        for candidate in ["RSI 45/55", "ADX <25", "ADX <30"]:
            delta = p[candidate] - p["BASELINE"]
            wins = int((delta > 0).sum())
            print(
                f"  {candidate:<10} wins={wins:2d}/{len(delta):2d} "
                f"avg_delta={delta.mean():+6.3f}pp"
            )

    print("\nDECISION RULE")
    print("Do not change the live bot from this run alone. ADX must show better")
    print("return/giveback behaviour and broad rolling consistency versus both the")
    print("current baseline and RSI before any live proposal is made.")
    print("Live bot remains unchanged.")


if __name__ == "__main__":
    main()
