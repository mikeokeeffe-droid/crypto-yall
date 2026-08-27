"""
rsi_targeted_backtest.py — Targeted rolling RSI robustness research.

Research only. No live executor imports and no trading actions.
Fetches each asset once, then reuses the exact same prepared 1h dataset for
all fee assumptions and rolling-window comparisons.
"""

from __future__ import annotations

import hashlib

import pandas as pd

import rsi_exit_12m_backtest as research

ASSETS = ["SOL-USD", "BTC-USD"]
WINDOW_CONFIGS = [(30, 15), (60, 30), (90, 30), (120, 30)]
FEE_RATES = [0.00035, 0.00045, 0.00060]
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


def fingerprint(df: pd.DataFrame) -> str:
    cols = ["Open", "High", "Low", "Close", "Volume"]
    payload = pd.util.hash_pandas_object(df[cols], index=True).values.tobytes()
    return hashlib.sha256(payload).hexdigest()[:16]


def main() -> None:
    print("=" * 100)
    print("TARGETED RSI FIXED-DATA ROBUSTNESS TEST — SOL + BTC")
    print("Research only | Live bot unchanged | No orders")
    print(f"History: {research.TEST_DAYS} days | Fees: {FEE_RATES}")
    print(f"Windows: {WINDOW_CONFIGS}")
    print("=" * 100)

    datasets: dict[str, pd.DataFrame] = {}
    allow_short_map: dict[str, bool] = {}

    # Fetch and prepare ONCE per asset. Every fee test below uses these exact bars.
    for ticker in ASSETS:
        raw = research.fetch_yahoo_1h(ticker)
        prepared = research.prepare_indicators(raw)
        test_end = prepared.index.max() + pd.Timedelta(hours=1)
        test_start = test_end - pd.Timedelta(days=research.TEST_DAYS)
        df = prepared[prepared.index >= test_start].copy()
        datasets[ticker] = df
        allow_short_map[ticker] = bool(research.get_asset_profile(ticker)["allow_short"])
        print(
            f"DATA {ticker}: bars={len(df)} start={df.index.min()} end={df.index.max()} "
            f"sha={fingerprint(df)}"
        )

    for fee in FEE_RATES:
        research.FEE_RATE = fee
        print("\n" + "=" * 100)
        print(f"FEE TEST: {fee * 100:.4f}% per side")
        print("=" * 100)

        rows = []
        for ticker in ASSETS:
            df = datasets[ticker]
            allow_short = allow_short_map[ticker]
            simulations = {}

            print(f"\n{ticker} | bars={len(df)} | sha={fingerprint(df)}")
            for variant, long_exit, short_exit in VARIANTS:
                returns, trades = research.simulate(
                    df,
                    allow_short=allow_short,
                    long_rsi_exit=long_exit,
                    short_rsi_exit=short_exit,
                )
                simulations[variant] = (returns, trades)
                fm = research.metrics(returns, trades)
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
                        wm = research.metrics(wret, wtrades)
                        rows.append({
                            "asset": ticker,
                            "window_days": window_days,
                            "window": window_name,
                            "variant": variant,
                            **wm,
                        })

        result = pd.DataFrame(rows)
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
                    other = "RSI 45/55" if variant == "RSI 50/50" else "RSI 50/50"
                    delta = pivot[variant] - pivot["BASELINE"]
                    wins = int((delta > 0).sum())
                    best = int(
                        ((pivot[variant] > pivot["BASELINE"]) & (pivot[variant] > pivot[other])).sum()
                    )
                    print(
                        f"  {window_days:3d}d {variant:<9}: wins {wins:2d}/{total:<2d} "
                        f"({wins / total * 100:5.1f}%) | outright best {best:2d}/{total:<2d} | "
                        f"avg {delta.mean():+6.3f}pp | median {delta.median():+6.3f}pp | "
                        f"worst {delta.min():+6.3f}pp"
                    )

    print("\nFINAL NOTE")
    print("All fee assumptions above used identical market bars for each asset.")
    print("Live bot remains unchanged.")


if __name__ == "__main__":
    main()
