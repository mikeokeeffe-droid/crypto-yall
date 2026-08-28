"""
exit_signal_family_backtest.py — research-only comparison of four exit-signal families.

Tests the remaining candidate families for Intraday 1h:
  2) ATR trailing stop
  3) EMA trend / slope confirmation after oscillator FLAT
  4) MACD histogram / line confirmation after oscillator FLAT
  5) Rolling VWAP deviation confirmation after oscillator FLAT

Safety: no executor imports, no trading keys, no order placement.

Method:
- Same Intraday 1h entries and fixed ATR emergency stop as current research baseline.
- ATR trailing variants add an independent trailing stop while preserving the
  current immediate oscillator exit.
- EMA/MACD/VWAP variants replace immediate oscillator exit with a pending FLAT
  confirmation. Pending FLAT is cancelled if oscillator momentum recovers.
- Fixed Yahoo dataset per asset within the run: 365 days plus warmup.
- Fee sensitivity: 0.035%, 0.045%, 0.060% per side.
- Rolling 30/60/90/120-day robustness.
- Older/newer half consistency.
- Recent Hyperliquid 1h validation (~4,900 closed candles).

This is screening research, not a live recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import rsi_exit_12m_backtest as research
from indicators import vwap_deviation
from intraday_data_loader import fetch_candles

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
    family: str
    mode: str
    param: float | int | None = None


RULES = [
    Rule("BASELINE", "BASELINE", "baseline"),
    # ATR trailing-stop family: added risk/profit protection, baseline flat exit remains immediate.
    Rule("ATR TRAIL 1.5", "ATR", "atr_trail", 1.5),
    Rule("ATR TRAIL 2.0", "ATR", "atr_trail", 2.0),
    Rule("ATR TRAIL 2.5", "ATR", "atr_trail", 2.5),
    Rule("ATR TRAIL 3.0", "ATR", "atr_trail", 3.0),
    # EMA family: confirmation after oscillator flat.
    Rule("EMA20 PRICE", "EMA", "ema_price", 20),
    Rule("EMA50 PRICE", "EMA", "ema_price", 50),
    Rule("EMA20 SLOPE1", "EMA", "ema_slope", 1),
    Rule("EMA20 SLOPE3", "EMA", "ema_slope", 3),
    Rule("EMA20/50 TREND", "EMA", "ema_trend"),
    # MACD family: confirmation after oscillator flat.
    Rule("MACD HIST SIGN", "MACD", "macd_hist_sign"),
    Rule("MACD HIST SLOPE1", "MACD", "macd_hist_slope", 1),
    Rule("MACD HIST SLOPE3", "MACD", "macd_hist_slope", 3),
    Rule("MACD LINE CROSS", "MACD", "macd_cross"),
    # VWAP family: rolling VWAP deviation confirmation after oscillator flat.
    Rule("VWAP20 SIGN", "VWAP", "vwap_sign", 20),
    Rule("VWAP20 0.25%", "VWAP", "vwap_threshold", 0.0025),
    Rule("VWAP20 0.50%", "VWAP", "vwap_threshold", 0.0050),
    Rule("VWAP50 SIGN", "VWAP", "vwap50_sign", 50),
]
RULE_MAP = {r.name: r for r in RULES}


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = research.prepare_indicators(df)
    close = out["Close"].astype(float)

    out["EMA20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
    out["EMA50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    out["MACD"] = ema12 - ema26
    out["MACD_SIGNAL"] = out["MACD"].ewm(span=9, adjust=False, min_periods=9).mean()
    out["MACD_HIST"] = out["MACD"] - out["MACD_SIGNAL"]

    out["VWAP20_DEV"] = vwap_deviation(
        out["Close"], out["High"], out["Low"], out["Volume"], period=20
    )
    out["VWAP50_DEV"] = vwap_deviation(
        out["Close"], out["High"], out["Low"], out["Volume"], period=50
    )
    return out


def trade_return(side: int, entry: float, exit_: float) -> float:
    return exit_ / entry - 1.0 if side == 1 else entry / exit_ - 1.0


def adverse_slope(values: np.ndarray, i: int, bars: int, side: int) -> bool:
    if i < bars:
        return False
    chunk = values[i - bars : i + 1]
    if np.isnan(chunk).any():
        return False
    if side == 1:
        return all(chunk[j] < chunk[j - 1] for j in range(1, len(chunk)))
    return all(chunk[j] > chunk[j - 1] for j in range(1, len(chunk)))


def confirm_flat(rule: Rule, side: int, i: int, arrays: dict[str, np.ndarray]) -> bool:
    price = arrays["close"][i]

    if rule.mode == "baseline":
        return True

    if rule.mode == "ema_price":
        ema = arrays[f"ema{int(rule.param)}"][i]
        if np.isnan(ema):
            return False
        return price < ema if side == 1 else price > ema

    if rule.mode == "ema_slope":
        return adverse_slope(arrays["ema20"], i, int(rule.param), side)

    if rule.mode == "ema_trend":
        fast = arrays["ema20"][i]
        slow = arrays["ema50"][i]
        if np.isnan(fast) or np.isnan(slow):
            return False
        return fast < slow if side == 1 else fast > slow

    if rule.mode == "macd_hist_sign":
        hist = arrays["macd_hist"][i]
        if np.isnan(hist):
            return False
        return hist < 0 if side == 1 else hist > 0

    if rule.mode == "macd_hist_slope":
        return adverse_slope(arrays["macd_hist"], i, int(rule.param), side)

    if rule.mode == "macd_cross":
        macd = arrays["macd"][i]
        signal = arrays["macd_signal"][i]
        if np.isnan(macd) or np.isnan(signal):
            return False
        return macd < signal if side == 1 else macd > signal

    if rule.mode == "vwap_sign":
        dev = arrays["vwap20"][i]
        if np.isnan(dev):
            return False
        return dev < 0 if side == 1 else dev > 0

    if rule.mode == "vwap_threshold":
        dev = arrays["vwap20"][i]
        threshold = float(rule.param)
        if np.isnan(dev):
            return False
        return dev < -threshold if side == 1 else dev > threshold

    if rule.mode == "vwap50_sign":
        dev = arrays["vwap50"][i]
        if np.isnan(dev):
            return False
        return dev < 0 if side == 1 else dev > 0

    raise ValueError(f"Unknown mode {rule.mode}")


def exit_reason(rule: Rule, side: int) -> str:
    if rule.mode == "baseline":
        return "oscillator exit"
    return f"flat + {rule.name}"


def simulate(
    df: pd.DataFrame,
    allow_short: bool,
    rule: Rule,
    fee_rate: float,
) -> tuple[pd.Series, list[research.Trade]]:
    idx = df.index
    arrays = {
        "close": df["Close"].to_numpy(dtype=float),
        "osc": df["TwoPole_Osc"].to_numpy(dtype=float),
        "atr": df["ATR"].to_numpy(dtype=float),
        "ema20": df["EMA20"].to_numpy(dtype=float),
        "ema50": df["EMA50"].to_numpy(dtype=float),
        "macd": df["MACD"].to_numpy(dtype=float),
        "macd_signal": df["MACD_SIGNAL"].to_numpy(dtype=float),
        "macd_hist": df["MACD_HIST"].to_numpy(dtype=float),
        "vwap20": df["VWAP20_DEV"].to_numpy(dtype=float),
        "vwap50": df["VWAP50_DEV"].to_numpy(dtype=float),
    }
    close = arrays["close"]
    osc = arrays["osc"]
    atr = arrays["atr"]

    n = len(df)
    position = np.zeros(n, dtype=int)
    fee_events = np.zeros(n, dtype=float)
    trades: list[research.Trade] = []

    side = 0
    entry_price = np.nan
    entry_i = -1
    peak_return = 0.0
    pending_flat = False
    highest_price = -np.inf
    lowest_price = np.inf

    for i in range(1, n):
        price = close[i]
        prev_osc = osc[i - 1]
        curr_osc = osc[i]
        atr_now = atr[i] if not np.isnan(atr[i]) else 0.0

        if side != 0:
            peak_return = max(peak_return, trade_return(side, entry_price, price))
            highest_price = max(highest_price, price)
            lowest_price = min(lowest_price, price)

        hard_exit = False
        hard_reason = ""
        if side == 1 and not np.isnan(entry_price):
            fixed_stop = entry_price - research.ATR_STOP_MULT * atr_now
            if atr_now > 0 and price <= fixed_stop:
                hard_exit = True
                hard_reason = "ATR stop"
        elif side == -1 and not np.isnan(entry_price):
            fixed_stop = entry_price + research.ATR_STOP_MULT * atr_now
            if atr_now > 0 and price >= fixed_stop:
                hard_exit = True
                hard_reason = "ATR stop"

        # ATR trailing stop is an independent family. It does not delay the
        # current oscillator exit; it only adds a possible earlier exit.
        if side != 0 and rule.mode == "atr_trail" and atr_now > 0 and not hard_exit:
            mult = float(rule.param)
            if side == 1:
                trail = highest_price - mult * atr_now
                if price <= trail:
                    hard_exit = True
                    hard_reason = rule.name
            else:
                trail = lowest_price + mult * atr_now
                if price >= trail:
                    hard_exit = True
                    hard_reason = rule.name

        oscillator_exit = (
            (side == 1 and prev_osc > 0 >= curr_osc)
            or (side == -1 and prev_osc < 0 <= curr_osc)
        )

        # Baseline and ATR-trail family preserve immediate oscillator exit.
        if side != 0 and rule.family in ("BASELINE", "ATR") and oscillator_exit:
            hard_exit = True
            hard_reason = "oscillator exit"

        # EMA/MACD/VWAP families use the oscillator exit as the FLAT event and
        # wait for their own confirmation, cancelling if momentum recovers.
        if side != 0 and rule.family in ("EMA", "MACD", "VWAP"):
            if oscillator_exit:
                pending_flat = True
            if pending_flat:
                if side == 1 and curr_osc > 0:
                    pending_flat = False
                elif side == -1 and curr_osc < 0:
                    pending_flat = False

        confirmed_exit = (
            side != 0
            and rule.family in ("EMA", "MACD", "VWAP")
            and pending_flat
            and confirm_flat(rule, side, i, arrays)
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
                    exit_reason=hard_reason if hard_exit else exit_reason(rule, side),
                    bars_held=i - entry_i,
                )
            )
            fee_events[i] += fee_rate
            side = 0
            entry_price = np.nan
            entry_i = -1
            peak_return = 0.0
            pending_flat = False
            highest_price = -np.inf
            lowest_price = np.inf

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
            highest_price = price
            lowest_price = price
            position[i] = 1
            fee_events[i] += fee_rate
            continue

        if allow_short and prev_osc >= research.OSC_UPPER > curr_osc:
            side = -1
            entry_price = price
            entry_i = i
            peak_return = 0.0
            pending_flat = False
            highest_price = price
            lowest_price = price
            position[i] = -1
            fee_events[i] += fee_rate

    pos_s = pd.Series(position, index=idx, dtype=float)
    gross_returns = pos_s.shift(1).fillna(0.0) * df["Close"].pct_change().fillna(0.0)
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


def trim_to_test_year(prepared: pd.DataFrame) -> pd.DataFrame:
    test_end = prepared.index.max() + pd.Timedelta(hours=1)
    test_start = test_end - pd.Timedelta(days=research.TEST_DAYS)
    return prepared[prepared.index >= test_start].copy()


def collect_yahoo() -> dict[str, pd.DataFrame]:
    data: dict[str, pd.DataFrame] = {}
    print("\nFIXED YAHOO DATASETS")
    for ticker in ASSETS:
        raw = research.fetch_yahoo_1h(ticker)
        df = trim_to_test_year(prepare(raw))
        data[ticker] = df
        fingerprint = pd.util.hash_pandas_object(
            df[["Open", "High", "Low", "Close", "Volume"]], index=True
        ).sum()
        print(
            f"{ticker:<13} bars={len(df):4d} {df.index.min()} -> {df.index.max()} "
            f"hash={int(fingerprint) & 0xffffffffffffffff:016x}"
        )
    return data


def run_sweep(data: dict[str, pd.DataFrame]):
    full_rows: list[dict] = []
    rolling_rows: list[dict] = []
    half_rows: list[dict] = []

    for ticker, df in data.items():
        allow_short = bool(research.get_asset_profile(ticker)["allow_short"])
        midpoint = df.index.min() + (df.index.max() - df.index.min()) / 2

        for fee in FEE_LEVELS:
            for rule in RULES:
                returns, trades = simulate(df, allow_short, rule, fee)
                full_rows.append(
                    {"asset": ticker, "fee": fee, "variant": rule.name, "family": rule.family, **research.metrics(returns, trades)}
                )

                for label, start, end in [
                    ("OLDER", df.index.min(), midpoint),
                    ("NEWER", midpoint, df.index.max() + pd.Timedelta(hours=1)),
                ]:
                    pr = returns[(returns.index >= start) & (returns.index < end)]
                    pt = [t for t in trades if start <= t.exit_time < end]
                    half_rows.append(
                        {"asset": ticker, "fee": fee, "variant": rule.name, "family": rule.family, "half": label, **research.metrics(pr, pt)}
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
                                "family": rule.family,
                                "window_days": window_days,
                                "window": window_name,
                                **research.metrics(wr, wt),
                            }
                        )

    return pd.DataFrame(full_rows), pd.DataFrame(rolling_rows), pd.DataFrame(half_rows)


def variant_stats(full: pd.DataFrame, rolling: pd.DataFrame, name: str, fee: float = NORMAL_FEE) -> dict:
    f = full[full.fee == fee]
    base = f[f.variant == "BASELINE"]
    cand = f[f.variant == name]

    r = rolling[(rolling.fee == fee) & (rolling.variant.isin(["BASELINE", name]))]
    p = r.pivot_table(
        index=["asset", "window_days", "window"], columns="variant", values="return_pct", aggfunc="first"
    ).dropna()
    delta = p[name] - p["BASELINE"]

    return {
        "ret": cand.return_pct.mean(),
        "delta": cand.return_pct.mean() - base.return_pct.mean(),
        "dd": cand.max_dd_pct.mean(),
        "dd_delta": cand.max_dd_pct.mean() - base.max_dd_pct.mean(),
        "gb": cand.avg_giveback_pct.mean(),
        "gb_delta": cand.avg_giveback_pct.mean() - base.avg_giveback_pct.mean(),
        "wins": int((delta > 0).sum()),
        "total": len(delta),
        "win_pct": float((delta > 0).mean() * 100.0),
        "avg_window_delta": float(delta.mean()),
        "median_window_delta": float(delta.median()),
        "worst_window_delta": float(delta.min()),
    }


def print_family_ranking(full: pd.DataFrame, rolling: pd.DataFrame) -> dict[str, str]:
    print("\n" + "=" * 120)
    print("FAMILY SCREEN — NORMAL FEE")
    print("=" * 120)
    base = full[(full.fee == NORMAL_FEE) & (full.variant == "BASELINE")]
    print(
        f"BASELINE return={base.return_pct.mean():+.2f}% DD={base.max_dd_pct.mean():+.2f}% "
        f"giveback={base.avg_giveback_pct.mean():.3f}%"
    )

    family_best: dict[str, str] = {}
    for family in ["ATR", "EMA", "MACD", "VWAP"]:
        candidates = []
        for rule in [r for r in RULES if r.family == family]:
            s = variant_stats(full, rolling, rule.name)
            candidates.append((s["win_pct"], s["avg_window_delta"], s["delta"], rule.name, s))
        candidates.sort(reverse=True)
        _, _, _, best_name, best = candidates[0]
        family_best[family] = best_name
        print(f"\n{family} — best: {best_name}")
        for _, _, _, name, s in candidates:
            print(
                f"  {name:<20} ret={s['ret']:+7.2f}% Δ={s['delta']:+7.2f}pp "
                f"DD={s['dd']:+7.2f}% ΔDD={s['dd_delta']:+6.2f}pp GB={s['gb']:.3f}% "
                f"roll={s['wins']:3d}/{s['total']:<3d} ({s['win_pct']:5.1f}%) "
                f"avgΔ={s['avg_window_delta']:+6.2f} medΔ={s['median_window_delta']:+6.2f} "
                f"worst={s['worst_window_delta']:+7.2f}"
            )
    return family_best


def print_fee_sensitivity(full: pd.DataFrame, family_best: dict[str, str]) -> None:
    print("\n" + "=" * 120)
    print("FEE SENSITIVITY — BEST RULE FROM EACH FAMILY")
    print("=" * 120)
    for fee in FEE_LEVELS:
        f = full[full.fee == fee]
        base = f[f.variant == "BASELINE"].return_pct.mean()
        print(f"\nFee {fee*100:.3f}%/side baseline={base:+.2f}%")
        for family, name in family_best.items():
            cand = f[f.variant == name].return_pct.mean()
            print(f"  {family:<5} {name:<20} return={cand:+7.2f}% Δ={cand-base:+7.2f}pp")


def print_window_detail(rolling: pd.DataFrame, family_best: dict[str, str]) -> None:
    print("\n" + "=" * 120)
    print("ROLLING ROBUSTNESS BY WINDOW LENGTH — NORMAL FEE")
    print("=" * 120)
    r = rolling[rolling.fee == NORMAL_FEE]
    for family, name in family_best.items():
        print(f"\n{family}: {name}")
        for days, _ in WINDOW_SPECS:
            q = r[(r.window_days == days) & (r.variant.isin(["BASELINE", name]))]
            p = q.pivot_table(index=["asset", "window"], columns="variant", values="return_pct", aggfunc="first").dropna()
            delta = p[name] - p["BASELINE"]
            print(
                f"  {days:3d}d {int((delta > 0).sum()):3d}/{len(delta):<3d} "
                f"({(delta > 0).mean()*100:5.1f}%) avg={delta.mean():+6.2f}pp "
                f"median={delta.median():+6.2f}pp worst={delta.min():+7.2f}pp"
            )


def print_asset_best(full: pd.DataFrame, rolling: pd.DataFrame) -> None:
    print("\n" + "=" * 120)
    print("BEST OF ATR / EMA / MACD / VWAP PER ASSET — NORMAL FEE")
    print("=" * 120)
    f = full[full.fee == NORMAL_FEE]
    r = rolling[rolling.fee == NORMAL_FEE]
    for asset in ASSETS:
        base = f[(f.asset == asset) & (f.variant == "BASELINE")].iloc[0]
        rows = []
        for rule in RULES[1:]:
            cand = f[(f.asset == asset) & (f.variant == rule.name)].iloc[0]
            q = r[
                (r.asset == asset)
                & (r.window_days.isin([60, 90, 120]))
                & (r.variant.isin(["BASELINE", rule.name]))
            ]
            p = q.pivot_table(index=["window_days", "window"], columns="variant", values="return_pct", aggfunc="first").dropna()
            delta = p[rule.name] - p["BASELINE"]
            rows.append(
                {
                    "name": rule.name,
                    "family": rule.family,
                    "delta": cand.return_pct - base.return_pct,
                    "roll": float((delta > 0).mean() * 100.0),
                    "avg": float(delta.mean()),
                    "dd": cand.max_dd_pct - base.max_dd_pct,
                    "gb": cand.avg_giveback_pct - base.avg_giveback_pct,
                }
            )
        best = pd.DataFrame(rows).sort_values(["roll", "avg", "delta"], ascending=False).iloc[0]
        print(
            f"{asset:<13} {best['family']:<5} {best['name']:<20} Δ12m={best['delta']:+7.2f}pp "
            f"roll60/90/120={best['roll']:5.1f}% avg={best['avg']:+6.2f}pp "
            f"ΔDD={best['dd']:+6.2f}pp ΔGB={best['gb']:+6.2f}pp"
        )


def print_half_consistency(half: pd.DataFrame, family_best: dict[str, str]) -> None:
    print("\n" + "=" * 120)
    print("OLDER / NEWER HALF — NORMAL FEE")
    print("=" * 120)
    h = half[half.fee == NORMAL_FEE]
    for name in ["BASELINE"] + list(family_best.values()):
        c = h[h.variant == name]
        older = c[c.half == "OLDER"].return_pct.mean()
        newer = c[c.half == "NEWER"].return_pct.mean()
        print(f"{name:<20} older={older:+8.2f}% newer={newer:+8.2f}%")


def side_metrics(trades: list[research.Trade], side: int) -> dict:
    selected = [t for t in trades if t.side == side]
    if not selected:
        return {"n": 0, "compound": 0.0, "giveback": 0.0, "bars": 0.0}
    compound = float(np.prod([1.0 + t.net_return for t in selected]) - 1.0) * 100.0
    return {
        "n": len(selected),
        "compound": compound,
        "giveback": float(np.mean([t.giveback for t in selected]) * 100.0),
        "bars": float(np.mean([t.bars_held for t in selected])),
    }


def print_side_diagnostics(data: dict[str, pd.DataFrame], family_best: dict[str, str]) -> None:
    print("\n" + "=" * 120)
    print("BTC / ETH LONG-SHORT DIAGNOSTICS — BEST FAMILY RULES")
    print("=" * 120)
    for asset in ["BTC-USD", "ETH-USD"]:
        df = data[asset]
        allow_short = True
        base_returns, base_trades = simulate(df, allow_short, RULE_MAP["BASELINE"], NORMAL_FEE)
        bm = research.metrics(base_returns, base_trades)
        print(f"\n{asset} baseline={bm['return_pct']:+.2f}%")
        for family, name in family_best.items():
            returns, trades = simulate(df, allow_short, RULE_MAP[name], NORMAL_FEE)
            m = research.metrics(returns, trades)
            long_m = side_metrics(trades, 1)
            short_m = side_metrics(trades, -1)
            print(
                f"  {family:<5} {name:<20} return={m['return_pct']:+7.2f}% Δ={m['return_pct']-bm['return_pct']:+7.2f}pp | "
                f"L n={long_m['n']:3d} cmp={long_m['compound']:+7.2f}% gb={long_m['giveback']:5.2f}% | "
                f"S n={short_m['n']:3d} cmp={short_m['compound']:+7.2f}% gb={short_m['giveback']:5.2f}%"
            )


def hyperliquid_validation(family_best: dict[str, str]) -> dict[str, dict]:
    candidates = list(family_best.values())
    print("\n" + "=" * 120)
    print("HYPERLIQUID RECENT VALIDATION — BEST RULE FROM EACH FAMILY")
    print("=" * 120)
    print("Candidates:", ", ".join(candidates))

    rows = []
    for asset in ASSETS:
        try:
            raw = fetch_candles(asset, interval="1h", lookback_hours=HL_LOOKBACK_HOURS)
            if raw.empty:
                print(f"{asset}: no data")
                continue
            df = prepare(raw)
            allow_short = bool(research.get_asset_profile(asset)["allow_short"])
            base_returns, base_trades = simulate(df, allow_short, RULE_MAP["BASELINE"], NORMAL_FEE)
            bm = research.metrics(base_returns, base_trades)
            print(f"\n{asset:<13} bars={len(df):4d} baseline={bm['return_pct']:+7.2f}%")

            for family, name in family_best.items():
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
                    wins += int(rwm["return_pct"] > bwm["return_pct"])
                    total += 1
                rows.append({"asset": asset, "family": family, "variant": name, "delta": delta, "wins": wins, "total": total})
                print(f"  {family:<5} {name:<20} return={m['return_pct']:+7.2f}% Δ={delta:+7.2f}pp 60d={wins}/{total}")
        except Exception as exc:
            print(f"ERROR {asset}: {exc}")

    result: dict[str, dict] = {}
    if rows:
        v = pd.DataFrame(rows)
        print("\nHYPERLIQUID FAMILY AGGREGATE")
        for family, name in family_best.items():
            c = v[v.family == family]
            wins = int(c.wins.sum())
            total = int(c.total.sum())
            summary = {
                "name": name,
                "mean_delta": float(c.delta.mean()),
                "positive_assets": int((c.delta > 0).sum()),
                "asset_total": len(c),
                "wins": wins,
                "total": total,
                "win_pct": wins / total * 100.0 if total else 0.0,
            }
            result[family] = summary
            print(
                f"{family:<5} {name:<20} meanΔ={summary['mean_delta']:+7.2f}pp "
                f"positiveAssets={summary['positive_assets']}/{summary['asset_total']} "
                f"60d={wins}/{total} ({summary['win_pct']:5.1f}%)"
            )
    return result


def final_scorecard(full: pd.DataFrame, rolling: pd.DataFrame, family_best: dict[str, str], hl: dict[str, dict]) -> None:
    print("\n" + "=" * 120)
    print("FINAL FAMILY SCORECARD — SCREENING ONLY")
    print("=" * 120)
    score_rows = []
    for family, name in family_best.items():
        s = variant_stats(full, rolling, name)
        h = hl.get(family, {})
        score_rows.append(
            {
                "family": family,
                "name": name,
                "yahoo_delta": s["delta"],
                "yahoo_roll": s["win_pct"],
                "yahoo_dd": s["dd_delta"],
                "hl_delta": h.get("mean_delta", np.nan),
                "hl_roll": h.get("win_pct", np.nan),
                "hl_assets": h.get("positive_assets", 0),
            }
        )
    score = pd.DataFrame(score_rows).sort_values(
        ["hl_roll", "yahoo_roll", "hl_delta", "yahoo_delta"], ascending=False
    )
    for i, (_, r) in enumerate(score.iterrows(), start=1):
        print(
            f"#{i} {r['family']:<5} {r['name']:<20} "
            f"Yahoo Δ={r['yahoo_delta']:+7.2f}pp roll={r['yahoo_roll']:5.1f}% ΔDD={r['yahoo_dd']:+6.2f}pp | "
            f"HL Δ={r['hl_delta']:+7.2f}pp roll={r['hl_roll']:5.1f}% assets+={int(r['hl_assets'])}/8"
        )
    print("\nLive strategy files were not changed.")
    print("Use this screen to decide which family deserves a dedicated out-of-sample test next.")


def main() -> None:
    print("=" * 120)
    print("EXIT SIGNAL FAMILY SCREEN — ATR / EMA / MACD / VWAP")
    print("Research only | Intraday 1h | Live bot unchanged | No keys | No orders")
    print(f"Rules={len(RULES)} | Yahoo={research.TEST_DAYS}d | HL recent={HL_LOOKBACK_HOURS}h | Fees={FEE_LEVELS}")
    print("=" * 120)

    data = collect_yahoo()
    full, rolling, half = run_sweep(data)
    family_best = print_family_ranking(full, rolling)
    print_fee_sensitivity(full, family_best)
    print_window_detail(rolling, family_best)
    print_asset_best(full, rolling)
    print_half_consistency(half, family_best)
    print_side_diagnostics(data, family_best)
    hl = hyperliquid_validation(family_best)
    final_scorecard(full, rolling, family_best, hl)


if __name__ == "__main__":
    main()
