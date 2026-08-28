"""
combined_exit_candidate_backtest.py — combined exit candidate research.

RESEARCH ONLY. No executor imports, no trading keys, no orders.

Purpose
-------
Now that DMI+ADX, ATR trailing stops and EMA slope have each shown useful
behaviour in screening, this script tests whether combining them improves the
Intraday 1h exit logic without simply curve-fitting one full-year result.

Design
------
- Same Intraday oscillator entries as live research baseline.
- Same fixed 2x ATR emergency stop.
- DMI+ADX and EMA are FLAT confirmations after oscillator zero-cross.
- ATR trailing stop is independent protection and can exit before FLAT.
- Pending FLAT confirmation is cancelled if oscillator momentum recovers.
- Yahoo 365d fixed dataset, three fee levels, 30/60/90/120d windows.
- Older 240d selection / newer ~125d untouched holdout check.
- Recent Hyperliquid ~4,900 closed 1h candles as a second data source.
- Coin-by-coin ranking plus broad/global ranking.

No live strategy files are modified.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import rsi_exit_12m_backtest as research
from dmi_adx_flat_exit_backtest import dmi_wilder
from intraday_data_loader import fetch_candles

FEES = [0.00035, 0.00045, 0.00060]
NORMAL_FEE = 0.00045
WINDOWS = [(30, 15), (60, 30), (90, 30), (120, 30)]
HL_LOOKBACK_HOURS = 4900
SELECTION_DAYS = 240

ASSETS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD",
    "LINK-USD", "SUI20947-USD", "XRP-USD", "ONDO-USD",
]


@dataclass(frozen=True)
class Rule:
    name: str
    flat_mode: str = "baseline"  # baseline, dmi, ema, dmi_and_ema, dmi_or_ema
    adx_max: float | None = None
    dmi_spread: float = 0.0
    atr_trail: float | None = None


RULES = [
    Rule("BASELINE"),
    Rule("DMI+ADX20", "dmi", 20.0),
    Rule("DMI+ADX25", "dmi", 25.0),
    Rule("DMI5+ADX25", "dmi", 25.0, 5.0),
    Rule("ATR1.5", "baseline", atr_trail=1.5),
    Rule("EMA20 SLOPE3", "ema"),
    Rule("DMI20 + ATR1.5", "dmi", 20.0, atr_trail=1.5),
    Rule("DMI25 + ATR1.5", "dmi", 25.0, atr_trail=1.5),
    Rule("DMI5/25 + ATR1.5", "dmi", 25.0, 5.0, 1.5),
    Rule("DMI20 & EMA", "dmi_and_ema", 20.0),
    Rule("DMI25 & EMA", "dmi_and_ema", 25.0),
    Rule("DMI20 OR EMA", "dmi_or_ema", 20.0),
    Rule("DMI25 OR EMA", "dmi_or_ema", 25.0),
    Rule("DMI20 + ATR + EMA", "dmi_and_ema", 20.0, atr_trail=1.5),
    Rule("DMI25 + ATR + EMA", "dmi_and_ema", 25.0, atr_trail=1.5),
    Rule("DMI20 OR EMA + ATR", "dmi_or_ema", 20.0, atr_trail=1.5),
    Rule("DMI25 OR EMA + ATR", "dmi_or_ema", 25.0, atr_trail=1.5),
]
RULE_MAP = {r.name: r for r in RULES}


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = research.prepare_indicators(df)
    dmi = dmi_wilder(out)
    out[["PLUS_DI", "MINUS_DI", "ADX"]] = dmi[["PLUS_DI", "MINUS_DI", "ADX"]]
    out["EMA20"] = out["Close"].astype(float).ewm(span=20, adjust=False, min_periods=20).mean()
    return out


def trade_return(side: int, entry: float, exit_: float) -> float:
    return exit_ / entry - 1.0 if side == 1 else entry / exit_ - 1.0


def dmi_confirms(rule: Rule, side: int, plus: np.ndarray, minus: np.ndarray, adx: np.ndarray, i: int) -> bool:
    vals = [plus[i], minus[i], adx[i]]
    if np.isnan(vals).any():
        return False
    adverse = (minus[i] - plus[i]) if side == 1 else (plus[i] - minus[i])
    if adverse <= rule.dmi_spread:
        return False
    return rule.adx_max is None or adx[i] < rule.adx_max


def ema_confirms(side: int, ema20: np.ndarray, i: int) -> bool:
    if i < 3:
        return False
    chunk = ema20[i - 3 : i + 1]
    if np.isnan(chunk).any():
        return False
    if side == 1:
        return all(chunk[j] < chunk[j - 1] for j in range(1, len(chunk)))
    return all(chunk[j] > chunk[j - 1] for j in range(1, len(chunk)))


def flat_confirms(rule: Rule, side: int, plus: np.ndarray, minus: np.ndarray, adx: np.ndarray, ema20: np.ndarray, i: int) -> bool:
    if rule.flat_mode == "baseline":
        return True
    dmi_ok = dmi_confirms(rule, side, plus, minus, adx, i)
    ema_ok = ema_confirms(side, ema20, i)
    if rule.flat_mode == "dmi":
        return dmi_ok
    if rule.flat_mode == "ema":
        return ema_ok
    if rule.flat_mode == "dmi_and_ema":
        return dmi_ok and ema_ok
    if rule.flat_mode == "dmi_or_ema":
        return dmi_ok or ema_ok
    raise ValueError(rule.flat_mode)


def simulate(df: pd.DataFrame, allow_short: bool, rule: Rule, fee: float):
    idx = df.index
    close = df["Close"].to_numpy(float)
    osc = df["TwoPole_Osc"].to_numpy(float)
    atr = df["ATR"].to_numpy(float)
    plus = df["PLUS_DI"].to_numpy(float)
    minus = df["MINUS_DI"].to_numpy(float)
    adx = df["ADX"].to_numpy(float)
    ema20 = df["EMA20"].to_numpy(float)

    n = len(df)
    position = np.zeros(n, dtype=int)
    fee_events = np.zeros(n, dtype=float)
    trades: list[research.Trade] = []

    side = 0
    entry_price = np.nan
    entry_i = -1
    peak_return = 0.0
    pending_flat = False
    highest = -np.inf
    lowest = np.inf

    for i in range(1, n):
        price = close[i]
        prev_osc, curr_osc = osc[i - 1], osc[i]
        atr_now = atr[i] if not np.isnan(atr[i]) else 0.0

        if side != 0:
            peak_return = max(peak_return, trade_return(side, entry_price, price))
            highest = max(highest, price)
            lowest = min(lowest, price)

        hard_exit = False
        reason = ""
        if side == 1 and atr_now > 0:
            if price <= entry_price - research.ATR_STOP_MULT * atr_now:
                hard_exit, reason = True, "ATR stop"
        elif side == -1 and atr_now > 0:
            if price >= entry_price + research.ATR_STOP_MULT * atr_now:
                hard_exit, reason = True, "ATR stop"

        if side != 0 and rule.atr_trail is not None and atr_now > 0 and not hard_exit:
            if side == 1 and price <= highest - rule.atr_trail * atr_now:
                hard_exit, reason = True, f"ATR trail {rule.atr_trail:g}"
            elif side == -1 and price >= lowest + rule.atr_trail * atr_now:
                hard_exit, reason = True, f"ATR trail {rule.atr_trail:g}"

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

        confirmed = (
            side != 0 and pending_flat
            and flat_confirms(rule, side, plus, minus, adx, ema20, i)
        )

        if side != 0 and (hard_exit or confirmed):
            gross = trade_return(side, entry_price, price)
            net = gross - 2.0 * fee
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
                    exit_reason=reason if hard_exit else f"flat + {rule.name}",
                    bars_held=i - entry_i,
                )
            )
            fee_events[i] += fee
            side = 0
            entry_price = np.nan
            entry_i = -1
            peak_return = 0.0
            pending_flat = False
            highest = -np.inf
            lowest = np.inf

        if side != 0:
            position[i] = side
            continue
        if np.isnan(prev_osc) or np.isnan(curr_osc):
            continue

        if prev_osc <= research.OSC_LOWER < curr_osc:
            side = 1
            entry_price = price
            entry_i = i
            position[i] = 1
            highest = lowest = price
            fee_events[i] += fee
            continue
        if allow_short and prev_osc >= research.OSC_UPPER > curr_osc:
            side = -1
            entry_price = price
            entry_i = i
            position[i] = -1
            highest = lowest = price
            fee_events[i] += fee

    pos = pd.Series(position, index=idx, dtype=float)
    gross_returns = pos.shift(1).fillna(0.0) * df["Close"].pct_change().fillna(0.0)
    return gross_returns - pd.Series(fee_events, index=idx), trades


def windows(index: pd.DatetimeIndex, days: int, step_days: int):
    cursor = index.min()
    final = index.max() + pd.Timedelta(hours=1)
    span = pd.Timedelta(days=days)
    step = pd.Timedelta(days=step_days)
    n = 1
    while cursor + span <= final:
        yield f"{days}d-W{n:02d}", cursor, cursor + span
        cursor += step
        n += 1


def trim_year(df: pd.DataFrame) -> pd.DataFrame:
    end = df.index.max() + pd.Timedelta(hours=1)
    return df[df.index >= end - pd.Timedelta(days=research.TEST_DAYS)].copy()


def collect_yahoo() -> dict[str, pd.DataFrame]:
    data = {}
    print("\nFIXED YAHOO DATASETS")
    for asset in ASSETS:
        df = trim_year(prepare(research.fetch_yahoo_1h(asset)))
        data[asset] = df
        fp = pd.util.hash_pandas_object(df[["Open", "High", "Low", "Close", "Volume"]], index=True).sum()
        print(f"{asset:<13} bars={len(df):4d} {df.index.min()} -> {df.index.max()} hash={int(fp)&0xffffffffffffffff:016x}")
    return data


def collect(data: dict[str, pd.DataFrame]):
    full, roll = [], []
    for asset, df in data.items():
        allow_short = bool(research.get_asset_profile(asset)["allow_short"])
        for fee in FEES:
            for rule in RULES:
                ret, trades = simulate(df, allow_short, rule, fee)
                full.append({"asset": asset, "fee": fee, "variant": rule.name, **research.metrics(ret, trades)})
                for days, step in WINDOWS:
                    for label, start, end in windows(df.index, days, step):
                        rr = ret[(ret.index >= start) & (ret.index < end)]
                        tt = [t for t in trades if start <= t.exit_time < end]
                        roll.append({"asset": asset, "fee": fee, "variant": rule.name, "window_days": days, "window": label, **research.metrics(rr, tt)})
    return pd.DataFrame(full), pd.DataFrame(roll)


def broad_stats(full: pd.DataFrame, roll: pd.DataFrame, name: str, fee: float = NORMAL_FEE) -> dict:
    f = full[full.fee == fee]
    base = f[f.variant == "BASELINE"]
    cand = f[f.variant == name]
    r = roll[(roll.fee == fee) & (roll.variant.isin(["BASELINE", name]))]
    p = r.pivot_table(index=["asset", "window_days", "window"], columns="variant", values="return_pct", aggfunc="first").dropna()
    d = p[name] - p["BASELINE"]
    return {
        "ret": cand.return_pct.mean(),
        "delta": cand.return_pct.mean() - base.return_pct.mean(),
        "dd": cand.max_dd_pct.mean(),
        "dd_delta": cand.max_dd_pct.mean() - base.max_dd_pct.mean(),
        "gb": cand.avg_giveback_pct.mean(),
        "gb_delta": cand.avg_giveback_pct.mean() - base.avg_giveback_pct.mean(),
        "wins": int((d > 0).sum()), "total": len(d), "wpct": float((d > 0).mean() * 100),
        "avgd": float(d.mean()), "medd": float(d.median()), "worst": float(d.min()),
    }


def print_global(full: pd.DataFrame, roll: pd.DataFrame) -> list[str]:
    print("\n" + "=" * 122)
    print("GLOBAL COMBINATION RANKING — NORMAL FEE")
    print("=" * 122)
    rows = []
    for rule in RULES[1:]:
        s = broad_stats(full, roll, rule.name)
        rows.append({"name": rule.name, **s})
    rank = pd.DataFrame(rows).sort_values(["wpct", "avgd", "delta"], ascending=False)
    print(f"{'RULE':<24} {'Δ12M':>8} {'ΔDD':>8} {'ΔGB':>8} {'ROLL':>12} {'AVGΔ':>8} {'MEDΔ':>8} {'WORST':>8}")
    for _, r in rank.iterrows():
        print(f"{r['name']:<24} {r['delta']:+8.2f} {r['dd_delta']:+8.2f} {r['gb_delta']:+8.3f} {int(r['wins']):3d}/{int(r['total']):<3d} {r['wpct']:5.1f}% {r['avgd']:+8.2f} {r['medd']:+8.2f} {r['worst']:+8.2f}")
    return rank.head(6).name.tolist()


def print_fee(full: pd.DataFrame, names: list[str]) -> None:
    print("\n" + "=" * 122)
    print("FEE SENSITIVITY — TOP COMBINATIONS")
    print("=" * 122)
    for fee in FEES:
        f = full[full.fee == fee]
        base = f[f.variant == "BASELINE"].return_pct.mean()
        print(f"Fee {fee*100:.3f}%/side baseline={base:+.2f}%")
        for name in names:
            c = f[f.variant == name].return_pct.mean()
            print(f"  {name:<24} return={c:+7.2f}% Δ={c-base:+7.2f}pp")


def selection_holdout(data: dict[str, pd.DataFrame]) -> dict[str, str]:
    print("\n" + "=" * 122)
    print("OLDER-DATA SELECTION -> NEWER UNTOUCHED HOLDOUT")
    print("Select each coin's rule using first 240 days only; report remaining newer period separately.")
    print("=" * 122)
    choices = {}
    for asset, df in data.items():
        allow_short = bool(research.get_asset_profile(asset)["allow_short"])
        cut = df.index.min() + pd.Timedelta(days=SELECTION_DAYS)
        select_df = df[df.index < cut]
        hold_df = df[df.index >= cut]

        select_results = []
        for rule in RULES:
            ret, trades = simulate(select_df, allow_short, rule, NORMAL_FEE)
            m = research.metrics(ret, trades)
            select_results.append((m["return_pct"], rule.name))
        select_results.sort(reverse=True)
        selected_return, selected_name = select_results[0]
        choices[asset] = selected_name

        bret, btr = simulate(hold_df, allow_short, RULE_MAP["BASELINE"], NORMAL_FEE)
        sret, strades = simulate(hold_df, allow_short, RULE_MAP[selected_name], NORMAL_FEE)
        bm = research.metrics(bret, btr)
        sm = research.metrics(sret, strades)
        print(f"{asset:<13} chose={selected_name:<24} select={selected_return:+7.2f}% | holdout baseline={bm['return_pct']:+7.2f}% chosen={sm['return_pct']:+7.2f}% Δ={sm['return_pct']-bm['return_pct']:+7.2f}pp")
    return choices


def print_asset_ranking(full: pd.DataFrame, roll: pd.DataFrame) -> None:
    print("\n" + "=" * 122)
    print("BEST COMBINATION PER COIN — FULL-YEAR SCREEN")
    print("=" * 122)
    f = full[full.fee == NORMAL_FEE]
    r = roll[roll.fee == NORMAL_FEE]
    for asset in ASSETS:
        base = f[(f.asset == asset) & (f.variant == "BASELINE")].iloc[0]
        rows = []
        for rule in RULES[1:]:
            c = f[(f.asset == asset) & (f.variant == rule.name)].iloc[0]
            q = r[(r.asset == asset) & (r.window_days.isin([60, 90, 120])) & (r.variant.isin(["BASELINE", rule.name]))]
            p = q.pivot_table(index=["window_days", "window"], columns="variant", values="return_pct", aggfunc="first").dropna()
            d = p[rule.name] - p["BASELINE"]
            rows.append({"name": rule.name, "delta": c.return_pct-base.return_pct, "roll": float((d>0).mean()*100), "avg": float(d.mean()), "dd": c.max_dd_pct-base.max_dd_pct, "gb": c.avg_giveback_pct-base.avg_giveback_pct})
        best = pd.DataFrame(rows).sort_values(["roll", "avg", "delta"], ascending=False).iloc[0]
        print(f"{asset:<13} {best['name']:<24} Δ12m={best['delta']:+7.2f}pp roll60/90/120={best['roll']:5.1f}% avg={best['avg']:+6.2f}pp ΔDD={best['dd']:+6.2f}pp ΔGB={best['gb']:+6.2f}pp")


def hyperliquid_validation(names: list[str], choices: dict[str, str]) -> dict[str, dict]:
    print("\n" + "=" * 122)
    print("RECENT HYPERLIQUID VALIDATION")
    print("=" * 122)
    candidates = []
    for n in names + list(choices.values()):
        if n != "BASELINE" and n not in candidates:
            candidates.append(n)
    candidates = candidates[:10]
    print("Candidates:", ", ".join(candidates))

    rows = []
    for asset in ASSETS:
        try:
            raw = fetch_candles(asset, interval="1h", lookback_hours=HL_LOOKBACK_HOURS)
            df = prepare(raw)
            allow_short = bool(research.get_asset_profile(asset)["allow_short"])
            br, bt = simulate(df, allow_short, RULE_MAP["BASELINE"], NORMAL_FEE)
            bm = research.metrics(br, bt)
            print(f"\n{asset:<13} bars={len(df):4d} baseline={bm['return_pct']:+7.2f}%")
            for name in candidates:
                rr, tt = simulate(df, allow_short, RULE_MAP[name], NORMAL_FEE)
                m = research.metrics(rr, tt)
                wins = total = 0
                for _, start, end in windows(df.index, 60, 30):
                    bwm = research.metrics(br[(br.index>=start)&(br.index<end)], [t for t in bt if start<=t.exit_time<end])
                    rwm = research.metrics(rr[(rr.index>=start)&(rr.index<end)], [t for t in tt if start<=t.exit_time<end])
                    wins += int(rwm["return_pct"] > bwm["return_pct"]); total += 1
                delta = m["return_pct"] - bm["return_pct"]
                rows.append({"asset":asset,"variant":name,"delta":delta,"wins":wins,"total":total})
                marker = " *SELECTED" if choices.get(asset) == name else ""
                print(f"  {name:<24} Δ={delta:+7.2f}pp 60d={wins}/{total}{marker}")
        except Exception as exc:
            print(f"ERROR {asset}: {exc}")

    result = {}
    if rows:
        v = pd.DataFrame(rows)
        print("\nHYPERLIQUID AGGREGATE")
        for name in candidates:
            c = v[v.variant == name]
            wins, total = int(c.wins.sum()), int(c.total.sum())
            result[name] = {"delta":float(c.delta.mean()),"positive":int((c.delta>0).sum()),"wins":wins,"total":total,"wpct":wins/total*100 if total else 0}
            print(f"{name:<24} meanΔ={c.delta.mean():+7.2f}pp assets+={(c.delta>0).sum()}/{len(c)} 60d={wins}/{total} ({wins/total*100 if total else 0:5.1f}%)")
    return result


def final_decision_table(full: pd.DataFrame, roll: pd.DataFrame, names: list[str], hl: dict[str, dict]) -> None:
    print("\n" + "=" * 122)
    print("FINAL RESEARCH SCORECARD")
    print("=" * 122)
    rows = []
    for name in names:
        s = broad_stats(full, roll, name)
        h = hl.get(name, {})
        rows.append({"name":name,"yd":s["delta"],"yr":s["wpct"],"dd":s["dd_delta"],"gb":s["gb_delta"],"hd":h.get("delta",np.nan),"hr":h.get("wpct",np.nan),"hp":h.get("positive",0)})
    score = pd.DataFrame(rows).sort_values(["hr","yr","hd","yd"], ascending=False)
    for i,(_,r) in enumerate(score.iterrows(),1):
        print(f"#{i} {r['name']:<24} Yahoo Δ={r['yd']:+7.2f}pp roll={r['yr']:5.1f}% ΔDD={r['dd']:+6.2f}pp ΔGB={r['gb']:+6.2f}pp | HL Δ={r['hd']:+7.2f}pp roll={r['hr']:5.1f}% assets+={int(r['hp'])}/8")
    print("\nNo live strategy files changed. This remains research-only.")


def main() -> None:
    print("=" * 122)
    print("COMBINED EXIT CANDIDATE TEST — DMI+ADX / ATR TRAIL / EMA")
    print("Research only | Intraday 1h | no keys | no orders | live bot unchanged")
    print(f"Rules={len(RULES)} Fees={FEES} Yahoo={research.TEST_DAYS}d Selection={SELECTION_DAYS}d HL={HL_LOOKBACK_HOURS}h")
    print("=" * 122)
    data = collect_yahoo()
    full, roll = collect(data)
    top = print_global(full, roll)
    print_fee(full, top)
    print_asset_ranking(full, roll)
    choices = selection_holdout(data)
    hl = hyperliquid_validation(top, choices)
    final_decision_table(full, roll, top, hl)


if __name__ == "__main__":
    main()
