"""
adx_rsi_flat_exit_backtest.py — full ADX FLAT-exit research for Intraday 1h.

RESEARCH ONLY. No live executor imports, no API keys, and no order placement.

This sweep tests:
- Current baseline oscillator exit
- RSI 45/55 reference
- ADX(14) thresholds 15/20/25/30/35/40
- Falling ADX for 1/2/3 bars
- Threshold + falling combinations
- Threshold OR falling combinations
- ADX + RSI combinations
- Fee sensitivity at 0.035% / 0.045% / 0.060% per side
- Rolling 30/60/90/120-day robustness
- Older/newer half consistency
- BTC/ETH long-vs-short ADX diagnostics
- Hyperliquid recent-candle validation of the strongest Yahoo candidates

ATR stops remain immediate. If oscillator momentum recovers before a pending
FLAT exit confirms, the pending exit is cancelled. Live bot remains unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import rsi_exit_12m_backtest as research
from intraday_data_loader import fetch_candles

ADX_PERIOD = 14
FEE_LEVELS = [0.00035, 0.00045, 0.00060]
NORMAL_FEE = 0.00045
WINDOW_SPECS = [(30, 15), (60, 30), (90, 30), (120, 30)]
HL_LOOKBACK_HOURS = 4900

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


@dataclass(frozen=True)
class Rule:
    name: str
    mode: str
    threshold: float | None = None
    falling_bars: int = 0
    scope: str = "all"


RULES = [
    Rule("BASELINE", "baseline"),
    Rule("RSI 45/55", "rsi"),
    Rule("ADX <15", "adx_threshold", 15.0),
    Rule("ADX <20", "adx_threshold", 20.0),
    Rule("ADX <25", "adx_threshold", 25.0),
    Rule("ADX <30", "adx_threshold", 30.0),
    Rule("ADX <35", "adx_threshold", 35.0),
    Rule("ADX <40", "adx_threshold", 40.0),
    Rule("ADX FALL 1", "adx_falling", falling_bars=1),
    Rule("ADX FALL 2", "adx_falling", falling_bars=2),
    Rule("ADX FALL 3", "adx_falling", falling_bars=3),
    Rule("ADX<25 & FALL", "adx_and_falling", 25.0, 1),
    Rule("ADX<30 & FALL", "adx_and_falling", 30.0, 1),
    Rule("ADX<25 OR FALL2", "adx_or_falling", 25.0, 2),
    Rule("ADX<30 OR FALL2", "adx_or_falling", 30.0, 2),
    Rule("ADX<25 & RSI", "adx_rsi_and", 25.0),
    Rule("ADX<30 & RSI", "adx_rsi_and", 30.0),
]
RULE_MAP = {r.name: r for r in RULES}


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


def adx_falling(adx: np.ndarray, i: int, bars: int) -> bool:
    if bars <= 0 or i < bars:
        return False
    values = adx[i - bars : i + 1]
    if np.isnan(values).any():
        return False
    return all(values[j] < values[j - 1] for j in range(1, len(values)))


def rsi_confirms(side: int, rsi_now: float) -> bool:
    if np.isnan(rsi_now):
        return False
    return (side == 1 and rsi_now < 45.0) or (side == -1 and rsi_now > 55.0)


def rule_confirms(
    rule: Rule,
    side: int,
    rsi_now: float,
    adx: np.ndarray,
    i: int,
) -> bool:
    if rule.scope == "long" and side == -1:
        return True
    if rule.scope == "short" and side == 1:
        return True

    adx_now = adx[i]
    below = (
        rule.threshold is not None
        and not np.isnan(adx_now)
        and adx_now < rule.threshold
    )
    falling = adx_falling(adx, i, rule.falling_bars)

    if rule.mode == "baseline":
        return True
    if rule.mode == "rsi":
        return rsi_confirms(side, rsi_now)
    if rule.mode == "adx_threshold":
        return below
    if rule.mode == "adx_falling":
        return falling
    if rule.mode == "adx_and_falling":
        return below and falling
    if rule.mode == "adx_or_falling":
        return below or falling
    if rule.mode == "adx_rsi_and":
        return below and rsi_confirms(side, rsi_now)
    raise ValueError(f"Unknown rule mode: {rule.mode}")


def rule_reason(rule: Rule, side: int) -> str:
    if rule.mode == "baseline":
        return "oscillator exit"
    if rule.mode == "rsi":
        return "flat + RSI<45" if side == 1 else "flat + RSI>55"
    if rule.mode == "adx_threshold":
        return f"flat + ADX<{rule.threshold:g}"
    if rule.mode == "adx_falling":
        return f"flat + ADX falling {rule.falling_bars}"
    if rule.mode == "adx_and_falling":
        return f"flat + ADX<{rule.threshold:g} and falling"
    if rule.mode == "adx_or_falling":
        return f"flat + ADX<{rule.threshold:g} or falling {rule.falling_bars}"
    if rule.mode == "adx_rsi_and":
        rsi_text = "RSI<45" if side == 1 else "RSI>55"
        return f"flat + ADX<{rule.threshold:g} and {rsi_text}"
    return rule.name


def simulate(
    df: pd.DataFrame,
    allow_short: bool,
    rule: Rule,
    fee_rate: float,
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

        if pending_flat:
            if side == 1 and curr_osc > 0:
                pending_flat = False
            elif side == -1 and curr_osc < 0:
                pending_flat = False

        confirmed_exit = (
            side != 0
            and pending_flat
            and rule_confirms(rule, side, rsi_now, adx, i)
        )

        if side != 0 and (hard_exit or confirmed_exit):
            gross = trade_return(side, entry_price, price)
            net = gross - (2.0 * fee_rate)
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
                    exit_reason=hard_reason if hard_exit else rule_reason(rule, side),
                    bars_held=i - entry_i,
                )
            )
            fee_events[i] += fee_rate
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

        if prev_osc <= research.OSC_LOWER < curr_osc:
            side = 1
            entry_price = price
            entry_i = i
            peak_return = 0.0
            pending_flat = False
            position[i] = 1
            fee_events[i] += fee_rate
            continue

        if allow_short and prev_osc >= research.OSC_UPPER > curr_osc:
            side = -1
            entry_price = price
            entry_i = i
            peak_return = 0.0
            pending_flat = False
            position[i] = -1
            fee_events[i] += fee_rate

    pos_s = pd.Series(position, index=idx, dtype=float)
    gross_returns = (
        pos_s.shift(1).fillna(0.0) * df["Close"].pct_change().fillna(0.0)
    )
    net_returns = gross_returns - pd.Series(fee_events, index=idx)
    return net_returns, trades


def rolling_windows(index: pd.DatetimeIndex, window_days: int, step_days: int):
    start = index.min()
    final = index.max() + pd.Timedelta(hours=1)
    window = pd.Timedelta(days=window_days)
    step = pd.Timedelta(days=step_days)
    cursor = start
    number = 1
    while cursor + window <= final:
        yield f"{window_days}d-W{number:02d}", cursor, cursor + window
        cursor += step
        number += 1


def side_metrics(trades: list[research.Trade], side: int) -> dict:
    selected = [t for t in trades if t.side == side]
    if not selected:
        return {"n": 0, "win": 0.0, "avg": 0.0, "compound": 0.0, "giveback": 0.0, "bars": 0.0}
    compound = float(np.prod([1.0 + t.net_return for t in selected]) - 1.0)
    return {
        "n": len(selected),
        "win": sum(t.net_return > 0 for t in selected) / len(selected) * 100.0,
        "avg": float(np.mean([t.net_return for t in selected]) * 100.0),
        "compound": compound * 100.0,
        "giveback": float(np.mean([t.giveback for t in selected]) * 100.0),
        "bars": float(np.mean([t.bars_held for t in selected])),
    }


def trim_to_test_year(prepared: pd.DataFrame) -> pd.DataFrame:
    test_end = prepared.index.max() + pd.Timedelta(hours=1)
    test_start = test_end - pd.Timedelta(days=research.TEST_DAYS)
    return prepared[prepared.index >= test_start].copy()


def collect_yahoo() -> dict[str, pd.DataFrame]:
    data: dict[str, pd.DataFrame] = {}
    print("\nYAHOO DATASET FINGERPRINTS")
    for ticker in ASSETS:
        raw = research.fetch_yahoo_1h(ticker)
        df = trim_to_test_year(prepare(raw))
        if len(df) < 5000:
            print(f"WARNING {ticker}: only {len(df)} bars")
        data[ticker] = df
        fingerprint = pd.util.hash_pandas_object(
            df[["Open", "High", "Low", "Close", "Volume"]], index=True
        ).sum()
        print(
            f"{ticker:<13} bars={len(df):4d} "
            f"{df.index.min()} -> {df.index.max()} hash={int(fingerprint) & 0xffffffffffffffff:016x}"
        )
    return data


def run_yahoo_sweep(data: dict[str, pd.DataFrame]):
    full_rows: list[dict] = []
    rolling_rows: list[dict] = []
    half_rows: list[dict] = []

    for ticker, df in data.items():
        allow_short = bool(research.get_asset_profile(ticker)["allow_short"])
        midpoint = df.index.min() + (df.index.max() - df.index.min()) / 2

        for fee in FEE_LEVELS:
            for rule in RULES:
                returns, trades = simulate(df, allow_short, rule, fee)
                m = research.metrics(returns, trades)
                full_rows.append({"asset": ticker, "fee": fee, "variant": rule.name, **m})

                for label, start, end in [
                    ("OLDER", df.index.min(), midpoint),
                    ("NEWER", midpoint, df.index.max() + pd.Timedelta(hours=1)),
                ]:
                    pr = returns[(returns.index >= start) & (returns.index < end)]
                    pt = [t for t in trades if start <= t.exit_time < end]
                    half_rows.append(
                        {"asset": ticker, "fee": fee, "variant": rule.name, "half": label, **research.metrics(pr, pt)}
                    )

                for window_days, step_days in WINDOW_SPECS:
                    for window_name, start, end in rolling_windows(df.index, window_days, step_days):
                        wr = returns[(returns.index >= start) & (returns.index < end)]
                        wt = [t for t in trades if start <= t.exit_time < end]
                        rolling_rows.append(
                            {
                                "asset": ticker,
                                "fee": fee,
                                "variant": rule.name,
                                "window_days": window_days,
                                "window": window_name,
                                **research.metrics(wr, wt),
                            }
                        )

    return pd.DataFrame(full_rows), pd.DataFrame(rolling_rows), pd.DataFrame(half_rows)


def print_global_summary(full: pd.DataFrame, rolling: pd.DataFrame) -> list[str]:
    normal = full[full.fee == NORMAL_FEE]
    base = normal[normal.variant == "BASELINE"]
    base_return = base.return_pct.mean()
    base_dd = base.max_dd_pct.mean()
    base_giveback = base.avg_giveback_pct.mean()

    print("\n" + "=" * 118)
    print("NORMAL-FEE GLOBAL SUMMARY — 12 MONTHS, MEAN ACROSS 8 ASSETS")
    print("=" * 118)
    print(
        f"BASELINE avg_return={base_return:+7.3f}% avg_DD={base_dd:+7.3f}% "
        f"avg_giveback={base_giveback:6.3f}%"
    )

    rows = []
    for rule in RULES[1:]:
        a = normal[normal.variant == rule.name]
        r = rolling[
            (rolling.fee == NORMAL_FEE) & (rolling.variant.isin(["BASELINE", rule.name]))
        ]
        pivot = r.pivot_table(
            index=["asset", "window_days", "window"], columns="variant", values="return_pct", aggfunc="first"
        ).dropna()
        delta = pivot[rule.name] - pivot["BASELINE"]
        rows.append(
            {
                "variant": rule.name,
                "avg_return": a.return_pct.mean(),
                "return_delta": a.return_pct.mean() - base_return,
                "avg_dd": a.max_dd_pct.mean(),
                "dd_delta": a.max_dd_pct.mean() - base_dd,
                "giveback": a.avg_giveback_pct.mean(),
                "giveback_delta": a.avg_giveback_pct.mean() - base_giveback,
                "rolling_wins": int((delta > 0).sum()),
                "rolling_total": len(delta),
                "rolling_pct": float((delta > 0).mean() * 100.0),
                "avg_window_delta": float(delta.mean()),
                "median_window_delta": float(delta.median()),
                "worst_window_delta": float(delta.min()),
            }
        )

    rank = pd.DataFrame(rows).sort_values(
        ["rolling_pct", "avg_window_delta", "return_delta"], ascending=False
    )

    print(
        f"{'RULE':<20} {'RET':>8} {'ΔRET':>8} {'DD':>8} {'ΔDD':>8} "
        f"{'GB':>7} {'ROLL':>11} {'AVGΔ':>8} {'MEDΔ':>8} {'WORST':>8}"
    )
    for _, r in rank.iterrows():
        print(
            f"{r['variant']:<20} {r['avg_return']:+8.2f} {r['return_delta']:+8.2f} "
            f"{r['avg_dd']:+8.2f} {r['dd_delta']:+8.2f} {r['giveback']:7.3f} "
            f"{int(r['rolling_wins']):3d}/{int(r['rolling_total']):<3d} "
            f"{r['avg_window_delta']:+8.2f} {r['median_window_delta']:+8.2f} "
            f"{r['worst_window_delta']:+8.2f}"
        )

    shortlist = rank[
        (rank.return_delta > 0)
        & (rank.rolling_pct >= 55.0)
        & (rank.dd_delta >= -1.0)
        & (rank.giveback_delta <= 0.60)
    ]
    print("\nBROAD ROBUSTNESS GATE")
    if shortlist.empty:
        print("No universal ADX rule passed all broad gates.")
    else:
        for _, r in shortlist.iterrows():
            print(
                f"PASS {r['variant']}: Δreturn={r['return_delta']:+.2f}pp, "
                f"rolling={r['rolling_pct']:.1f}%, ΔDD={r['dd_delta']:+.2f}pp, "
                f"Δgiveback={r['giveback_delta']:+.3f}pp"
            )

    return rank.variant.head(5).tolist()


def print_fee_sensitivity(full: pd.DataFrame) -> None:
    print("\n" + "=" * 118)
    print("FEE SENSITIVITY — MEAN RETURN DELTA VS BASELINE")
    print("=" * 118)
    for fee in FEE_LEVELS:
        f = full[full.fee == fee]
        baseline = f[f.variant == "BASELINE"].return_pct.mean()
        candidates = []
        for rule in RULES[1:]:
            value = f[f.variant == rule.name].return_pct.mean()
            candidates.append((value - baseline, rule.name, value))
        candidates.sort(reverse=True)
        print(f"\nFee {fee * 100:.3f}%/side | baseline={baseline:+.2f}%")
        for delta, name, value in candidates[:8]:
            print(f"  {name:<20} return={value:+7.2f}% Δ={delta:+7.2f}pp")


def print_window_robustness(rolling: pd.DataFrame, candidate_names: list[str]) -> None:
    print("\n" + "=" * 118)
    print("ROLLING ROBUSTNESS BY WINDOW LENGTH — NORMAL FEE")
    print("=" * 118)
    normal = rolling[rolling.fee == NORMAL_FEE]
    for name in candidate_names:
        print(f"\n{name}")
        for days, _ in WINDOW_SPECS:
            r = normal[
                (normal.window_days == days) & (normal.variant.isin(["BASELINE", name]))
            ]
            p = r.pivot_table(
                index=["asset", "window"], columns="variant", values="return_pct", aggfunc="first"
            ).dropna()
            delta = p[name] - p["BASELINE"]
            print(
                f"  {days:3d}d wins={int((delta > 0).sum()):3d}/{len(delta):<3d} "
                f"({(delta > 0).mean()*100:5.1f}%) avg={delta.mean():+6.2f}pp "
                f"median={delta.median():+6.2f}pp worst={delta.min():+6.2f}pp"
            )


def print_asset_selection(full: pd.DataFrame, rolling: pd.DataFrame, half: pd.DataFrame) -> dict[str, str]:
    print("\n" + "=" * 118)
    print("ASSET-SPECIFIC ROBUSTNESS — BEST ADX RULE PER COIN")
    print("=" * 118)
    normal_full = full[full.fee == NORMAL_FEE]
    high_full = full[full.fee == max(FEE_LEVELS)]
    normal_roll = rolling[rolling.fee == NORMAL_FEE]
    normal_half = half[half.fee == NORMAL_FEE]
    selected: dict[str, str] = {}

    for asset in ASSETS:
        baseline_full = normal_full[
            (normal_full.asset == asset) & (normal_full.variant == "BASELINE")
        ].iloc[0]
        baseline_high = high_full[
            (high_full.asset == asset) & (high_full.variant == "BASELINE")
        ].iloc[0]
        candidates = []

        for rule in RULES[2:]:
            c = normal_full[
                (normal_full.asset == asset) & (normal_full.variant == rule.name)
            ].iloc[0]
            ch = high_full[
                (high_full.asset == asset) & (high_full.variant == rule.name)
            ].iloc[0]
            r = normal_roll[
                (normal_roll.asset == asset)
                & (normal_roll.window_days.isin([60, 90, 120]))
                & (normal_roll.variant.isin(["BASELINE", rule.name]))
            ]
            p = r.pivot_table(
                index=["window_days", "window"], columns="variant", values="return_pct", aggfunc="first"
            ).dropna()
            delta = p[rule.name] - p["BASELINE"]
            rolling_pct = float((delta > 0).mean() * 100.0)

            newer = normal_half[
                (normal_half.asset == asset)
                & (normal_half.half == "NEWER")
                & (normal_half.variant == rule.name)
            ].iloc[0]
            newer_base = normal_half[
                (normal_half.asset == asset)
                & (normal_half.half == "NEWER")
                & (normal_half.variant == "BASELINE")
            ].iloc[0]
            candidates.append(
                {
                    "name": rule.name,
                    "delta": c.return_pct - baseline_full.return_pct,
                    "high_delta": ch.return_pct - baseline_high.return_pct,
                    "roll_pct": rolling_pct,
                    "roll_avg": float(delta.mean()),
                    "dd_delta": c.max_dd_pct - baseline_full.max_dd_pct,
                    "gb_delta": c.avg_giveback_pct - baseline_full.avg_giveback_pct,
                    "newer_delta": newer.return_pct - newer_base.return_pct,
                }
            )

        cand = pd.DataFrame(candidates).sort_values(
            ["roll_pct", "roll_avg", "delta"], ascending=False
        )
        best = cand.iloc[0]
        selected[asset] = str(best["name"])
        status = "STRONG" if (
            best["delta"] > 0
            and best["high_delta"] > 0
            and best["roll_pct"] >= 65
            and best["dd_delta"] >= -3.0
        ) else "MIXED"
        print(
            f"{asset:<13} {status:<6} {best['name']:<20} "
            f"Δ12m={best['delta']:+7.2f}pp highFee={best['high_delta']:+7.2f}pp "
            f"roll60/90/120={best['roll_pct']:5.1f}% avg={best['roll_avg']:+6.2f}pp "
            f"ΔDD={best['dd_delta']:+6.2f}pp ΔGB={best['gb_delta']:+6.2f}pp "
            f"newer={best['newer_delta']:+6.2f}pp"
        )
    return selected


def print_side_diagnostics(data: dict[str, pd.DataFrame]) -> None:
    print("\n" + "=" * 118)
    print("BTC / ETH SIDE-SPECIFIC ADX DIAGNOSTICS — NORMAL FEE")
    print("=" * 118)
    for asset in ["BTC-USD", "ETH-USD"]:
        df = data[asset]
        base_returns, base_trades = simulate(df, True, RULE_MAP["BASELINE"], NORMAL_FEE)
        base_m = research.metrics(base_returns, base_trades)
        print(f"\n{asset} baseline return={base_m['return_pct']:+.2f}%")
        for threshold in [20.0, 25.0, 30.0, 35.0]:
            for scope in ["long", "short"]:
                rule = Rule(
                    f"ADX<{threshold:g} {scope.upper()} ONLY", "adx_threshold", threshold, scope=scope
                )
                returns, trades = simulate(df, True, rule, NORMAL_FEE)
                m = research.metrics(returns, trades)
                sm = side_metrics(trades, 1 if scope == "long" else -1)
                wins = 0
                total = 0
                deltas = []
                for _, start, end in rolling_windows(df.index, 60, 30):
                    br = base_returns[(base_returns.index >= start) & (base_returns.index < end)]
                    rr = returns[(returns.index >= start) & (returns.index < end)]
                    bm = research.metrics(br, [t for t in base_trades if start <= t.exit_time < end])
                    rm = research.metrics(rr, [t for t in trades if start <= t.exit_time < end])
                    if bm and rm:
                        d = rm["return_pct"] - bm["return_pct"]
                        deltas.append(d)
                        wins += int(d > 0)
                        total += 1
                print(
                    f"  {rule.name:<19} return={m['return_pct']:+7.2f}% "
                    f"Δ={m['return_pct']-base_m['return_pct']:+6.2f}pp "
                    f"60d={wins:2d}/{total:<2d} avgΔ={np.mean(deltas):+6.2f}pp | "
                    f"{scope} n={sm['n']:3d} compound={sm['compound']:+7.2f}% "
                    f"gb={sm['giveback']:5.2f}% bars={sm['bars']:5.1f}"
                )


def print_half_consistency(half: pd.DataFrame, candidate_names: list[str]) -> None:
    print("\n" + "=" * 118)
    print("OLDER / NEWER HALF CONSISTENCY — NORMAL FEE, MEAN ACROSS ASSETS")
    print("=" * 118)
    h = half[half.fee == NORMAL_FEE]
    for name in ["BASELINE"] + candidate_names:
        c = h[h.variant == name]
        older = c[c.half == "OLDER"].return_pct.mean()
        newer = c[c.half == "NEWER"].return_pct.mean()
        print(f"{name:<20} older={older:+8.2f}% newer={newer:+8.2f}%")


def hyperliquid_validation(yahoo_top: list[str]) -> None:
    names = []
    for name in yahoo_top + ["ADX <25", "ADX <30", "ADX <35"]:
        if name not in names and name in RULE_MAP:
            names.append(name)
    names = names[:6]

    print("\n" + "=" * 118)
    print("HYPERLIQUID RECENT-CANDLE VALIDATION — ~204 DAYS, NORMAL FEE")
    print("=" * 118)
    print("Candidates:", ", ".join(names))

    rows = []
    for asset in ASSETS:
        try:
            raw = fetch_candles(asset, interval="1h", lookback_hours=HL_LOOKBACK_HOURS)
            if raw.empty:
                print(f"{asset}: no Hyperliquid candles")
                continue
            df = prepare(raw)
            allow_short = bool(research.get_asset_profile(asset)["allow_short"])
            base_returns, base_trades = simulate(df, allow_short, RULE_MAP["BASELINE"], NORMAL_FEE)
            bm = research.metrics(base_returns, base_trades)
            print(
                f"\n{asset:<13} bars={len(df):4d} baseline={bm['return_pct']:+7.2f}% DD={bm['max_dd_pct']:+7.2f}%"
            )
            for name in names:
                returns, trades = simulate(df, allow_short, RULE_MAP[name], NORMAL_FEE)
                m = research.metrics(returns, trades)
                delta = m["return_pct"] - bm["return_pct"]
                wins = 0
                total = 0
                for _, start, end in rolling_windows(df.index, 60, 30):
                    br = base_returns[(base_returns.index >= start) & (base_returns.index < end)]
                    rr = returns[(returns.index >= start) & (returns.index < end)]
                    bwm = research.metrics(br, [t for t in base_trades if start <= t.exit_time < end])
                    rwm = research.metrics(rr, [t for t in trades if start <= t.exit_time < end])
                    if bwm and rwm:
                        wins += int(rwm["return_pct"] > bwm["return_pct"])
                        total += 1
                rows.append({"asset": asset, "variant": name, "delta": delta, "wins": wins, "total": total})
                print(
                    f"  {name:<20} return={m['return_pct']:+7.2f}% Δ={delta:+7.2f}pp 60d={wins}/{total}"
                )
        except Exception as exc:
            print(f"ERROR Hyperliquid {asset}: {exc}")

    if rows:
        v = pd.DataFrame(rows)
        print("\nHYPERLIQUID AGGREGATE")
        for name in names:
            c = v[v.variant == name]
            if c.empty:
                continue
            wins = int(c.wins.sum())
            total = int(c.total.sum())
            print(
                f"{name:<20} meanΔ={c.delta.mean():+7.2f}pp assets_positive={(c.delta > 0).sum()}/{len(c)} "
                f"60d={wins}/{total} ({wins/total*100 if total else 0:5.1f}%)"
            )


def main() -> None:
    print("=" * 118)
    print("FULL ADX FLAT-EXIT RESEARCH SWEEP — INTRADAY 1H")
    print("Research only | Live bot unchanged | No trading keys | No orders")
    print(f"History: {research.TEST_DAYS} days Yahoo + recent Hyperliquid validation")
    print(
        "Fees: " + ", ".join(f"{f*100:.3f}%/side" for f in FEE_LEVELS)
        + " | Rolling windows: 30/60/90/120 days"
    )
    print(f"Rules tested: {len(RULES)}")
    print("=" * 118)

    data = collect_yahoo()
    full, rolling, half = run_yahoo_sweep(data)
    top = print_global_summary(full, rolling)
    print_fee_sensitivity(full)
    print_window_robustness(rolling, top)
    selected = print_asset_selection(full, rolling, half)
    print_side_diagnostics(data)
    print_half_consistency(half, top)
    hyperliquid_validation(top)

    print("\n" + "=" * 118)
    print("FINAL RESEARCH NOTES")
    print("=" * 118)
    print("Asset-specific best rules from Yahoo robustness ranking:")
    for asset, rule in selected.items():
        print(f"  {asset:<13} {rule}")
    print("No live strategy files or executors were changed by this research.")
    print("Any live proposal must still be reviewed before implementation.")


if __name__ == "__main__":
    main()
