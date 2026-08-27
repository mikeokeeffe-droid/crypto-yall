"""
BTC asymmetric RSI exit research.

RESEARCH ONLY. No live executor imports, no keys, no orders.
Tests whether RSI confirmation should apply to BTC shorts only rather than to
both long and short exits.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import rsi_exit_12m_backtest as research

FEE_RATES = [0.00035, 0.00045, 0.00060]
WINDOW_CONFIGS = [(30, 15), (60, 30), (90, 30), (120, 30)]
VARIANTS = [
    ("BASELINE", None, None),
    ("LONG RSI ONLY", 45.0, None),
    ("SHORT RSI ONLY", None, 55.0),
    ("RSI BOTH 45/55", 45.0, 55.0),
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


def trade_summary(trades):
    if not trades:
        return (0, 0.0, 0.0, 0.0, 0.0)
    net = np.array([t.net_return for t in trades], dtype=float)
    giveback = np.array([t.giveback for t in trades], dtype=float)
    bars = np.array([t.bars_held for t in trades], dtype=float)
    return (
        len(trades),
        float((net > 0).mean() * 100.0),
        float(np.mean(net) * 100.0),
        float(np.mean(giveback) * 100.0),
        float(np.mean(bars)),
    )


def main() -> None:
    raw = research.fetch_yahoo_1h("BTC-USD")
    prepared = research.prepare_indicators(raw)
    test_end = prepared.index.max() + pd.Timedelta(hours=1)
    test_start = test_end - pd.Timedelta(days=research.TEST_DAYS)
    df = prepared[prepared.index >= test_start].copy()
    allow_short = bool(research.get_asset_profile("BTC-USD")["allow_short"])

    print("=" * 100)
    print("BTC ASYMMETRIC RSI EXIT RESEARCH")
    print("Research only | Live bot unchanged | No orders")
    print(f"Bars: {len(df)} | {df.index.min()} -> {df.index.max()}")
    print("=" * 100)

    midpoint = df.index.min() + (df.index.max() - df.index.min()) / 2

    for fee in FEE_RATES:
        research.FEE_RATE = fee
        print("\n" + "=" * 100)
        print(f"FEE {fee * 100:.4f}% PER SIDE")
        print("=" * 100)

        simulations = {}
        for name, long_exit, short_exit in VARIANTS:
            returns, trades = research.simulate(
                df,
                allow_short=allow_short,
                long_rsi_exit=long_exit,
                short_rsi_exit=short_exit,
            )
            simulations[name] = (returns, trades)
            m = research.metrics(returns, trades)
            print(
                f"FULL {name:<15} return={m.get('return_pct', 0):+8.3f}% "
                f"DD={m.get('max_dd_pct', 0):+8.3f}% trades={m.get('trades', 0):3d} "
                f"win={m.get('win_rate_pct', 0):5.1f}% giveback={m.get('avg_giveback_pct', 0):6.3f}% "
                f"bars={m.get('avg_bars', 0):5.1f}"
            )

            longs = [t for t in trades if t.side == 1]
            shorts = [t for t in trades if t.side == -1]
            for label, group in [("LONG", longs), ("SHORT", shorts)]:
                n, wr, avg, gb, bars = trade_summary(group)
                print(
                    f"  {label:<5} n={n:3d} win={wr:5.1f}% avg={avg:+6.3f}% "
                    f"giveback={gb:6.3f}% bars={bars:5.1f}"
                )

            for label, start, end in [
                ("OLDER", df.index.min(), midpoint),
                ("NEWER", midpoint, df.index.max() + pd.Timedelta(hours=1)),
            ]:
                r = returns[(returns.index >= start) & (returns.index < end)]
                t = [trade for trade in trades if start <= trade.exit_time < end]
                pm = research.metrics(r, t)
                print(
                    f"  {label:<5} return={pm.get('return_pct', 0):+8.3f}% "
                    f"DD={pm.get('max_dd_pct', 0):+8.3f}% trades={pm.get('trades', 0):3d}"
                )

        print("\nROLLING ROBUSTNESS VS BASELINE")
        base_returns, base_trades = simulations["BASELINE"]
        for window_days, step_days in WINDOW_CONFIGS:
            windows = list(rolling_windows(df.index, window_days, step_days))
            for candidate in ["LONG RSI ONLY", "SHORT RSI ONLY", "RSI BOTH 45/55"]:
                cand_returns, cand_trades = simulations[candidate]
                deltas = []
                for _, start, end in windows:
                    br = base_returns[(base_returns.index >= start) & (base_returns.index < end)]
                    bt = [t for t in base_trades if start <= t.exit_time < end]
                    cr = cand_returns[(cand_returns.index >= start) & (cand_returns.index < end)]
                    ct = [t for t in cand_trades if start <= t.exit_time < end]
                    bm = research.metrics(br, bt)
                    cm = research.metrics(cr, ct)
                    deltas.append(cm.get("return_pct", 0.0) - bm.get("return_pct", 0.0))

                a = np.array(deltas, dtype=float)
                wins = int((a > 0).sum())
                print(
                    f"  {window_days:3d}d {candidate:<15} wins={wins:2d}/{len(a):2d} "
                    f"({wins/len(a)*100:5.1f}%) avg={a.mean():+6.3f}pp "
                    f"median={np.median(a):+6.3f}pp worst={a.min():+6.3f}pp"
                )

    print("\nDECISION RULE")
    print("Prefer the simpler asymmetric rule only if it improves robustness across")
    print("fees and windows and preserves the stronger recent-period performance.")
    print("Live bot remains unchanged.")


if __name__ == "__main__":
    main()
