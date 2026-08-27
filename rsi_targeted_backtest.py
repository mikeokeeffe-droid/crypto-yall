"""
rsi_targeted_backtest.py — Targeted rolling RSI robustness research.

Research only. No live executor imports and no trading actions.
Tests SOL and BTC across several rolling-window lengths. Fees are supplied by
BACKTEST_FEE_RATE from the research workflow matrix.
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
WINDOW_CONFIGS = [(30, 15), (60, 30), (90, 30), (120, 30)]
VARIANTS = [
    ("BASELINE", None, None),
    ("RSI 50/50", 50.0, 50.0),
    ("RSI 45/55", 45.0, 55.0),
]


def rolling_windows(index: pd.DatetimeIndex, window_days: int, step_days: int):
    start = index.min()
    final = index.max() + pd.Timedelta(hours=1)
    window = pd.Timedelta(days=window_days)
    step = pd.Timedelta(days=step_days)
    cursor = start
    number = 1
    while cursor + window <= final:
        yield f"W{number:02d}", cursor, cursor + window
        cursor += step
        number += 1


def main() -> None:
    print("=" * 96)
    print("TARGETED RSI MULTI-WINDOW ROBUSTNESS TEST — SOL + BTC")
    print("Research only | Live bot unchanged | No orders")
    print(f"History: {TEST_DAYS} days | Fee: {FEE_RATE * 100:.4f}% per side")
    print(f"Windows: {WINDOW_CONFIGS}")
    print("=" * 96)

    rows = []
    full_rows = []

    for ticker in ASSETS:
        raw = fetch_yahoo_1h(ticker)
        prepared = prepare_indicators(raw)
        test_end = prepared.index.max() + pd.Timedelta(hours=1)
        test_start = test_end - pd.Timedelta(days=TEST_DAYS)
        df = prepared[prepared.index >= test_start].copy()
        allow_short = bool(get_asset_profile(ticker)["allow_short"])

        print(f"\n{ticker}: {len(df)} closed 1h bars [{df.index.min()} -> {df.index.max()}]")

        simulations = {}
        for variant, long_exit, short_exit in VARIANTS:
            returns, trades = simulate(
                df,
                allow_short=allow_short,
                long_rsi_exit=long_exit,
                short_rsi_exit=short_exit,
            )
            simulations[variant] = (returns, trades)
            fm = metrics(returns, trades)
            full_rows.append({"asset": ticker, "variant": variant, **fm})
            print(
                f"  FULL {variant:<10} return={fm.get('return_pct', 0):+8.3f}% "
                f"DD={fm.get('max_dd_pct', 0):+8.3f}% trades={fm.get('trades', 0):4d} "
                f"giveback={fm.get('avg_giveback_pct', 0):6.3f}%"
            )

        for window_days, step_days in WINDOW_CONFIGS:
            for window_name, start, end in rolling_windows(df.index, window_days, step_days):
                for variant, _, _ in VARIANTS:
                    returns, trades = simulations[variant]
                    wret = returns[(returns.index >= start) & (returns.index < end)]
                    wtrades = [t for t in trades if start <= t.exit_time < end]
                    wm = metrics(wret, wtrades)
                    rows.append({
                        "asset": ticker,
                        "window_days": window_days,
                        "step_days": step_days,
                        "window": window_name,
                        "variant": variant,
                        **wm,
                    })

    result = pd.DataFrame(rows)
    if result.empty:
        raise RuntimeError("No targeted rolling results were produced")

    print("\nROBUSTNESS SUMMARY BY WINDOW LENGTH")
    for asset in ASSETS:
        print(f"\n{asset}")
        for window_days, _ in WINDOW_CONFIGS:
            subset = result[(result.asset == asset) & (result.window_days == window_days)]
            pivot = subset.pivot_table(
                index="window",
                columns="variant",
                values="return_pct",
                aggfunc="first",
            ).dropna()
            total = len(pivot)
            if not total:
                continue

            for variant in ["RSI 50/50", "RSI 45/55"]:
                delta = pivot[variant] - pivot["BASELINE"]
                wins = int((delta > 0).sum())
                best = int(
                    (
                        (pivot[variant] > pivot["BASELINE"])
                        & (pivot[variant] > pivot[[v for v in ["RSI 50/50", "RSI 45/55"] if v != variant][0]])
                    ).sum()
                )
                print(
                    f"  {window_days:3d}d {variant:<9}: wins {wins:2d}/{total:<2d} "
                    f"({wins / total * 100:5.1f}%) | outright best {best:2d}/{total:<2d} | "
                    f"avg delta {delta.mean():+6.3f}pp | median {delta.median():+6.3f}pp | "
                    f"worst {delta.min():+6.3f}pp"
                )

    print("\nDECISION RULE")
    print("Do not change live logic unless an RSI rule remains better across multiple")
    print("window lengths and fee assumptions without an unacceptable risk trade-off.")
    print("Live bot remains unchanged.")


if __name__ == "__main__":
    main()
