"""
rsi_targeted_backtest.py — Targeted rolling RSI robustness research.

Research only. No live executor imports and no trading actions.

Focus:
  - SOL-USD
  - BTC-USD

Compare:
  - BASELINE
  - RSI 50/50
  - RSI 45/55

Method:
  - 12 months of 1-hour Yahoo data
  - 60-day rolling windows
  - 30-day step between windows
  - fees included
  - ATR stops remain immediate

The goal is to test consistency, not just one headline return.
"""

from __future__ import annotations

import pandas as pd

from rsi_exit_12m_backtest import (
    FEE_RATE,
    TEST_DAYS,
    fetch_yahoo_1h,
    get_asset_profile,
    metrics,
    prepare_indicators,
    simulate,
)


ASSETS = ["SOL-USD", "BTC-USD"]
WINDOW_DAYS = 60
STEP_DAYS = 30
VARIANTS = [
    ("BASELINE", None, None),
    ("RSI 50/50", 50.0, 50.0),
    ("RSI 45/55", 45.0, 55.0),
]


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
    print("=" * 92)
    print("TARGETED RSI ROBUSTNESS TEST — SOL + BTC")
    print("Research only | Live bot unchanged | No orders")
    print(f"History: {TEST_DAYS} days | Window: {WINDOW_DAYS}d | Step: {STEP_DAYS}d")
    print(f"Fee assumption: {FEE_RATE * 100:.4f}% per side")
    print("=" * 92)

    rows = []

    for ticker in ASSETS:
        raw = fetch_yahoo_1h(ticker)
        prepared = prepare_indicators(raw)
        test_end = prepared.index.max() + pd.Timedelta(hours=1)
        test_start = test_end - pd.Timedelta(days=TEST_DAYS)
        df = prepared[prepared.index >= test_start].copy()

        profile = get_asset_profile(ticker)
        allow_short = bool(profile["allow_short"])

        print(
            f"\n{ticker}: {len(df)} closed 1h bars "
            f"[{df.index.min()} -> {df.index.max()}]"
        )

        for variant, long_exit, short_exit in VARIANTS:
            full_returns, full_trades = simulate(
                df,
                allow_short=allow_short,
                long_rsi_exit=long_exit,
                short_rsi_exit=short_exit,
            )
            full_metrics = metrics(full_returns, full_trades)
            print(
                f"  FULL {variant:<10} "
                f"return={full_metrics.get('return_pct', 0):+8.3f}% "
                f"DD={full_metrics.get('max_dd_pct', 0):+8.3f}% "
                f"trades={full_metrics.get('trades', 0):4d} "
                f"giveback={full_metrics.get('avg_giveback_pct', 0):6.3f}%"
            )

            for window_name, start, end in rolling_windows(df.index):
                wret = full_returns[
                    (full_returns.index >= start)
                    & (full_returns.index < end)
                ]
                wtrades = [
                    t for t in full_trades
                    if start <= t.exit_time < end
                ]
                wm = metrics(wret, wtrades)
                rows.append({
                    "asset": ticker,
                    "window": window_name,
                    "start": start,
                    "end": end,
                    "variant": variant,
                    **wm,
                })

    result = pd.DataFrame(rows)
    if result.empty:
        raise RuntimeError("No targeted rolling results were produced")

    pivot = result.pivot_table(
        index=["asset", "window"],
        columns="variant",
        values="return_pct",
        aggfunc="first",
    ).reset_index()

    print("\nROLLING 60-DAY RETURNS")
    print(
        pivot.to_string(
            index=False,
            float_format=lambda x: f"{x:,.3f}",
        )
    )

    print("\nROBUSTNESS SUMMARY")
    for asset in ASSETS:
        a = pivot[pivot["asset"] == asset].dropna().copy()
        total = len(a)
        if not total:
            continue

        wins_5050 = int((a["RSI 50/50"] > a["BASELINE"]).sum())
        wins_4555 = int((a["RSI 45/55"] > a["BASELINE"]).sum())
        best_5050 = int(
            (
                (a["RSI 50/50"] > a["BASELINE"])
                & (a["RSI 50/50"] > a["RSI 45/55"])
            ).sum()
        )
        best_4555 = int(
            (
                (a["RSI 45/55"] > a["BASELINE"])
                & (a["RSI 45/55"] > a["RSI 50/50"])
            ).sum()
        )

        print(f"\n{asset}")
        print(f"  RSI 50/50 beat baseline: {wins_5050}/{total} windows")
        print(f"  RSI 45/55 beat baseline: {wins_4555}/{total} windows")
        print(f"  RSI 50/50 was outright best: {best_5050}/{total} windows")
        print(f"  RSI 45/55 was outright best: {best_4555}/{total} windows")

        # Average return delta gives size of the improvement, not just count.
        delta_5050 = float((a["RSI 50/50"] - a["BASELINE"]).mean())
        delta_4555 = float((a["RSI 45/55"] - a["BASELINE"]).mean())
        print(f"  Avg 50/50 return delta: {delta_5050:+.3f} percentage points")
        print(f"  Avg 45/55 return delta: {delta_4555:+.3f} percentage points")

    print("\nDECISION RULE")
    print("Do not promote RSI live unless it wins across a clear majority of rolling")
    print("windows and the improvement is large enough to justify added giveback/risk.")
    print("Live bot remains unchanged by this research run.")


if __name__ == "__main__":
    main()
