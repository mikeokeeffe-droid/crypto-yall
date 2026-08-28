"""
additional_exit_signal_backtest.py — additional exit-signal screening.

RESEARCH ONLY. No executor imports, no keys, no order placement.

Families tested:
1) Supertrend (ATR-based trend flip)
2) Choppiness Index (trend-loss confirmation after oscillator FLAT)
3) Donchian trailing channel exits
4) OBV / volume-trend confirmation after oscillator FLAT

Method mirrors the existing Intraday 1h research baseline:
- same oscillator entries
- same fixed 2x ATR emergency stop
- fees at 0.035%, 0.045%, 0.060% per side
- Yahoo 365-day fixed dataset
- rolling 30/60/90/120-day robustness
- recent Hyperliquid ~4,900 closed 1h candles

No live strategy files are changed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import rsi_exit_12m_backtest as research
from indicators import average_true_range
from intraday_data_loader import fetch_candles

FEES = [0.00035, 0.00045, 0.00060]
NORMAL_FEE = 0.00045
WINDOWS = [(30, 15), (60, 30), (90, 30), (120, 30)]
HL_LOOKBACK_HOURS = 4900

ASSETS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD",
    "LINK-USD", "SUI20947-USD", "XRP-USD", "ONDO-USD",
]


@dataclass(frozen=True)
class Rule:
    name: str
    family: str
    mode: str
    p1: float | int | None = None
    p2: float | int | None = None


RULES = [
    Rule("BASELINE", "BASELINE", "baseline"),
    Rule("SUPERTREND 10x2", "SUPERTREND", "supertrend", 10, 2.0),
    Rule("SUPERTREND 10x3", "SUPERTREND", "supertrend", 10, 3.0),
    Rule("SUPERTREND 14x2", "SUPERTREND", "supertrend", 14, 2.0),
    Rule("SUPERTREND 14x3", "SUPERTREND", "supertrend", 14, 3.0),
    Rule("CHOP14 >55", "CHOP", "chop", 14, 55.0),
    Rule("CHOP14 >60", "CHOP", "chop", 14, 60.0),
    Rule("CHOP14 >65", "CHOP", "chop", 14, 65.0),
    Rule("CHOP21 >60", "CHOP", "chop", 21, 60.0),
    Rule("DONCHIAN 10", "DONCHIAN", "donchian", 10),
    Rule("DONCHIAN 20", "DONCHIAN", "donchian", 20),
    Rule("DONCHIAN 40", "DONCHIAN", "donchian", 40),
    Rule("OBV EMA20", "OBV", "obv_ema", 20),
    Rule("OBV SLOPE3", "OBV", "obv_slope", 3),
    Rule("OBV SLOPE5", "OBV", "obv_slope", 5),
]
RULE_MAP = {r.name: r for r in RULES}


def true_range(df: pd.DataFrame) -> pd.Series:
    h = df["High"].astype(float)
    l = df["Low"].astype(float)
    c = df["Close"].astype(float)
    pc = c.shift(1)
    return pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)


def choppiness(df: pd.DataFrame, period: int) -> pd.Series:
    tr = true_range(df)
    tr_sum = tr.rolling(period, min_periods=period).sum()
    hh = df["High"].astype(float).rolling(period, min_periods=period).max()
    ll = df["Low"].astype(float).rolling(period, min_periods=period).min()
    span = (hh - ll).replace(0, np.nan)
    out = 100.0 * np.log10(tr_sum / span) / np.log10(period)
    return out.replace([np.inf, -np.inf], np.nan)


def supertrend_direction(df: pd.DataFrame, period: int, mult: float) -> pd.Series:
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    atr = average_true_range(high, low, close, period=period).astype(float)
    mid = (high + low) / 2.0
    basic_upper = mid + mult * atr
    basic_lower = mid - mult * atr

    upper = basic_upper.copy()
    lower = basic_lower.copy()
    direction = pd.Series(np.nan, index=df.index, dtype=float)

    for i in range(1, len(df)):
        if np.isnan(atr.iloc[i]):
            continue
        prev_close = close.iloc[i-1]
        if np.isnan(upper.iloc[i-1]) or basic_upper.iloc[i] < upper.iloc[i-1] or prev_close > upper.iloc[i-1]:
            upper.iloc[i] = basic_upper.iloc[i]
        else:
            upper.iloc[i] = upper.iloc[i-1]
        if np.isnan(lower.iloc[i-1]) or basic_lower.iloc[i] > lower.iloc[i-1] or prev_close < lower.iloc[i-1]:
            lower.iloc[i] = basic_lower.iloc[i]
        else:
            lower.iloc[i] = lower.iloc[i-1]

        prev_dir = direction.iloc[i-1]
        if np.isnan(prev_dir):
            direction.iloc[i] = 1.0 if close.iloc[i] >= mid.iloc[i] else -1.0
        elif prev_dir > 0:
            direction.iloc[i] = -1.0 if close.iloc[i] < lower.iloc[i] else 1.0
        else:
            direction.iloc[i] = 1.0 if close.iloc[i] > upper.iloc[i] else -1.0
    return direction.ffill()


def obv_series(df: pd.DataFrame) -> pd.Series:
    close = df["Close"].astype(float)
    vol = df["Volume"].astype(float).fillna(0.0)
    direction = np.sign(close.diff()).fillna(0.0)
    return (direction * vol).cumsum()


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = research.prepare_indicators(df)
    for p in [14, 21]:
        out[f"CHOP{p}"] = choppiness(out, p)
    for period, mult in [(10,2.0),(10,3.0),(14,2.0),(14,3.0)]:
        out[f"ST_{period}_{mult:g}"] = supertrend_direction(out, period, mult)
    for p in [10,20,40]:
        out[f"DON_LOW_{p}"] = out["Low"].astype(float).rolling(p, min_periods=p).min().shift(1)
        out[f"DON_HIGH_{p}"] = out["High"].astype(float).rolling(p, min_periods=p).max().shift(1)
    out["OBV"] = obv_series(out)
    out["OBV_EMA20"] = out["OBV"].ewm(span=20, adjust=False, min_periods=20).mean()
    return out


def trade_return(side: int, entry: float, exit_: float) -> float:
    return exit_ / entry - 1.0 if side == 1 else entry / exit_ - 1.0


def adverse_slope(values: np.ndarray, i: int, bars: int, side: int) -> bool:
    if i < bars:
        return False
    x = values[i-bars:i+1]
    if np.isnan(x).any():
        return False
    if side == 1:
        return all(x[j] < x[j-1] for j in range(1, len(x)))
    return all(x[j] > x[j-1] for j in range(1, len(x)))


def flat_confirms(rule: Rule, side: int, i: int, a: dict[str, np.ndarray]) -> bool:
    if rule.mode == "baseline":
        return True
    if rule.mode == "chop":
        v = a[f"chop{int(rule.p1)}"][i]
        return not np.isnan(v) and v > float(rule.p2)
    if rule.mode == "obv_ema":
        obv, ema = a["obv"][i], a["obv_ema20"][i]
        if np.isnan(obv) or np.isnan(ema):
            return False
        return obv < ema if side == 1 else obv > ema
    if rule.mode == "obv_slope":
        return adverse_slope(a["obv"], i, int(rule.p1), side)
    raise ValueError(rule.mode)


def simulate(df: pd.DataFrame, allow_short: bool, rule: Rule, fee: float):
    idx = df.index
    a = {
        "close": df["Close"].to_numpy(float),
        "osc": df["TwoPole_Osc"].to_numpy(float),
        "atr": df["ATR"].to_numpy(float),
        "chop14": df["CHOP14"].to_numpy(float),
        "chop21": df["CHOP21"].to_numpy(float),
        "obv": df["OBV"].to_numpy(float),
        "obv_ema20": df["OBV_EMA20"].to_numpy(float),
    }
    for period, mult in [(10,2.0),(10,3.0),(14,2.0),(14,3.0)]:
        a[f"st_{period}_{mult:g}"] = df[f"ST_{period}_{mult:g}"].to_numpy(float)
    for p in [10,20,40]:
        a[f"don_low_{p}"] = df[f"DON_LOW_{p}"].to_numpy(float)
        a[f"don_high_{p}"] = df[f"DON_HIGH_{p}"].to_numpy(float)

    close, osc, atr = a["close"], a["osc"], a["atr"]
    n = len(df)
    position = np.zeros(n, dtype=int)
    fee_events = np.zeros(n, dtype=float)
    trades: list[research.Trade] = []
    side = 0
    entry_price = np.nan
    entry_i = -1
    peak_return = 0.0
    pending_flat = False

    for i in range(1,n):
        price = close[i]
        prev_osc, curr_osc = osc[i-1], osc[i]
        atr_now = atr[i] if not np.isnan(atr[i]) else 0.0
        if side != 0:
            peak_return = max(peak_return, trade_return(side, entry_price, price))

        exit_now = False
        reason = ""
        if side == 1 and atr_now > 0 and price <= entry_price - research.ATR_STOP_MULT*atr_now:
            exit_now, reason = True, "ATR stop"
        elif side == -1 and atr_now > 0 and price >= entry_price + research.ATR_STOP_MULT*atr_now:
            exit_now, reason = True, "ATR stop"

        # Independent exits: Supertrend and Donchian can act before oscillator FLAT.
        if side != 0 and not exit_now and rule.mode == "supertrend":
            st = a[f"st_{int(rule.p1)}_{float(rule.p2):g}"][i]
            if not np.isnan(st) and ((side == 1 and st < 0) or (side == -1 and st > 0)):
                exit_now, reason = True, rule.name
        if side != 0 and not exit_now and rule.mode == "donchian":
            p = int(rule.p1)
            low, high = a[f"don_low_{p}"][i], a[f"don_high_{p}"][i]
            if side == 1 and not np.isnan(low) and price < low:
                exit_now, reason = True, rule.name
            elif side == -1 and not np.isnan(high) and price > high:
                exit_now, reason = True, rule.name

        oscillator_exit = (
            (side == 1 and prev_osc > 0 >= curr_osc)
            or (side == -1 and prev_osc < 0 <= curr_osc)
        )

        # Baseline preserves immediate oscillator exit. Supertrend/Donchian are
        # additive protection and also preserve the current oscillator exit.
        if side != 0 and rule.family in ("BASELINE","SUPERTREND","DONCHIAN") and oscillator_exit and not exit_now:
            exit_now, reason = True, "oscillator exit"

        # CHOP/OBV use oscillator FLAT as a pending confirmation event.
        if side != 0 and rule.family in ("CHOP","OBV"):
            if oscillator_exit:
                pending_flat = True
            if pending_flat:
                if side == 1 and curr_osc > 0:
                    pending_flat = False
                elif side == -1 and curr_osc < 0:
                    pending_flat = False
            if pending_flat and flat_confirms(rule, side, i, a):
                exit_now, reason = True, f"flat + {rule.name}"

        if side != 0 and exit_now:
            gross = trade_return(side, entry_price, price)
            net = gross - 2.0*fee
            trades.append(research.Trade(
                side=side, entry_time=idx[entry_i], exit_time=idx[i],
                entry_price=float(entry_price), exit_price=float(price),
                gross_return=float(gross), net_return=float(net),
                peak_return=float(peak_return), giveback=float(peak_return-net),
                exit_reason=reason, bars_held=i-entry_i,
            ))
            fee_events[i] += fee
            side = 0; entry_price=np.nan; entry_i=-1; peak_return=0.0; pending_flat=False

        if side != 0:
            position[i] = side
            continue
        if np.isnan(prev_osc) or np.isnan(curr_osc):
            continue
        if prev_osc <= research.OSC_LOWER < curr_osc:
            side=1; entry_price=price; entry_i=i; position[i]=1; fee_events[i]+=fee; pending_flat=False
            continue
        if allow_short and prev_osc >= research.OSC_UPPER > curr_osc:
            side=-1; entry_price=price; entry_i=i; position[i]=-1; fee_events[i]+=fee; pending_flat=False

    pos = pd.Series(position, index=idx, dtype=float)
    gross_returns = pos.shift(1).fillna(0.0) * df["Close"].pct_change().fillna(0.0)
    return gross_returns - pd.Series(fee_events, index=idx), trades


def windows(index: pd.DatetimeIndex, days: int, step_days: int):
    cursor=index.min(); final=index.max()+pd.Timedelta(hours=1)
    span=pd.Timedelta(days=days); step=pd.Timedelta(days=step_days); n=1
    while cursor+span <= final:
        yield f"{days}d-W{n:02d}", cursor, cursor+span
        cursor += step; n += 1


def trim_year(df: pd.DataFrame) -> pd.DataFrame:
    end=df.index.max()+pd.Timedelta(hours=1)
    return df[df.index >= end-pd.Timedelta(days=research.TEST_DAYS)].copy()


def collect_yahoo():
    data={}
    print("\nFIXED YAHOO DATASETS")
    for asset in ASSETS:
        df=trim_year(prepare(research.fetch_yahoo_1h(asset)))
        data[asset]=df
        fp=pd.util.hash_pandas_object(df[["Open","High","Low","Close","Volume"]],index=True).sum()
        print(f"{asset:<13} bars={len(df):4d} hash={int(fp)&0xffffffffffffffff:016x}")
    return data


def run_sweep(data):
    full=[]; roll=[]
    for asset,df in data.items():
        allow_short=bool(research.get_asset_profile(asset)["allow_short"])
        for fee in FEES:
            for rule in RULES:
                ret,trades=simulate(df,allow_short,rule,fee)
                full.append({"asset":asset,"fee":fee,"variant":rule.name,"family":rule.family,**research.metrics(ret,trades)})
                for days,step in WINDOWS:
                    for label,start,end in windows(df.index,days,step):
                        rr=ret[(ret.index>=start)&(ret.index<end)]
                        tt=[t for t in trades if start<=t.exit_time<end]
                        roll.append({"asset":asset,"fee":fee,"variant":rule.name,"family":rule.family,"window_days":days,"window":label,**research.metrics(rr,tt)})
    return pd.DataFrame(full),pd.DataFrame(roll)


def stats(full,roll,name,fee=NORMAL_FEE):
    f=full[full.fee==fee]; base=f[f.variant=="BASELINE"]; cand=f[f.variant==name]
    r=roll[(roll.fee==fee)&(roll.variant.isin(["BASELINE",name]))]
    p=r.pivot_table(index=["asset","window_days","window"],columns="variant",values="return_pct",aggfunc="first").dropna()
    d=p[name]-p["BASELINE"]
    return {
        "ret":cand.return_pct.mean(),"delta":cand.return_pct.mean()-base.return_pct.mean(),
        "dd":cand.max_dd_pct.mean(),"dd_delta":cand.max_dd_pct.mean()-base.max_dd_pct.mean(),
        "gb":cand.avg_giveback_pct.mean(),"gb_delta":cand.avg_giveback_pct.mean()-base.avg_giveback_pct.mean(),
        "wins":int((d>0).sum()),"total":len(d),"wpct":float((d>0).mean()*100),
        "avgd":float(d.mean()),"medd":float(d.median()),"worst":float(d.min()),
    }


def print_screen(full,roll):
    print("\n"+"="*120); print("FAMILY SCREEN — NORMAL FEE"); print("="*120)
    family_best={}
    for family in ["SUPERTREND","CHOP","DONCHIAN","OBV"]:
        rows=[]
        for rule in [r for r in RULES if r.family==family]:
            s=stats(full,roll,rule.name); rows.append((s["wpct"],s["avgd"],s["delta"],rule.name,s))
        rows.sort(reverse=True); family_best[family]=rows[0][3]
        print(f"\n{family} best={rows[0][3]}")
        for _,_,_,name,s in rows:
            print(f"  {name:<20} Δ12m={s['delta']:+7.2f}pp ΔDD={s['dd_delta']:+6.2f}pp ΔGB={s['gb_delta']:+6.2f}pp roll={s['wins']:3d}/{s['total']:<3d} ({s['wpct']:5.1f}%) avgΔ={s['avgd']:+6.2f} medΔ={s['medd']:+6.2f} worst={s['worst']:+7.2f}")
    return family_best


def print_fee(full,best):
    print("\n"+"="*120); print("FEE SENSITIVITY"); print("="*120)
    for fee in FEES:
        f=full[full.fee==fee]; base=f[f.variant=="BASELINE"].return_pct.mean()
        print(f"Fee {fee*100:.3f}%/side baseline={base:+.2f}%")
        for family,name in best.items():
            c=f[f.variant==name].return_pct.mean()
            print(f"  {family:<10} {name:<20} Δ={c-base:+7.2f}pp")


def asset_best(full,roll):
    print("\n"+"="*120); print("BEST NEW SIGNAL PER COIN"); print("="*120)
    f=full[full.fee==NORMAL_FEE]; r=roll[roll.fee==NORMAL_FEE]
    for asset in ASSETS:
        base=f[(f.asset==asset)&(f.variant=="BASELINE")].iloc[0]; rows=[]
        for rule in RULES[1:]:
            c=f[(f.asset==asset)&(f.variant==rule.name)].iloc[0]
            q=r[(r.asset==asset)&(r.window_days.isin([60,90,120]))&(r.variant.isin(["BASELINE",rule.name]))]
            p=q.pivot_table(index=["window_days","window"],columns="variant",values="return_pct",aggfunc="first").dropna(); d=p[rule.name]-p["BASELINE"]
            rows.append({"family":rule.family,"name":rule.name,"delta":c.return_pct-base.return_pct,"roll":float((d>0).mean()*100),"avg":float(d.mean()),"dd":c.max_dd_pct-base.max_dd_pct})
        b=pd.DataFrame(rows).sort_values(["roll","avg","delta"],ascending=False).iloc[0]
        print(f"{asset:<13} {b['family']:<10} {b['name']:<20} Δ12m={b['delta']:+7.2f}pp roll={b['roll']:5.1f}% avg={b['avg']:+6.2f}pp ΔDD={b['dd']:+6.2f}pp")


def hl_validation(best):
    print("\n"+"="*120); print("HYPERLIQUID RECENT VALIDATION"); print("="*120)
    rows=[]
    for asset in ASSETS:
        try:
            df=prepare(fetch_candles(asset,interval="1h",lookback_hours=HL_LOOKBACK_HOURS))
            allow_short=bool(research.get_asset_profile(asset)["allow_short"])
            br,bt=simulate(df,allow_short,RULE_MAP["BASELINE"],NORMAL_FEE); bm=research.metrics(br,bt)
            print(f"\n{asset:<13} baseline={bm['return_pct']:+7.2f}%")
            for family,name in best.items():
                rr,tt=simulate(df,allow_short,RULE_MAP[name],NORMAL_FEE); m=research.metrics(rr,tt)
                wins=total=0
                for _,start,end in windows(df.index,60,30):
                    bwm=research.metrics(br[(br.index>=start)&(br.index<end)],[t for t in bt if start<=t.exit_time<end])
                    rwm=research.metrics(rr[(rr.index>=start)&(rr.index<end)],[t for t in tt if start<=t.exit_time<end])
                    wins += int(rwm["return_pct"]>bwm["return_pct"]); total += 1
                delta=m["return_pct"]-bm["return_pct"]
                rows.append({"asset":asset,"family":family,"name":name,"delta":delta,"wins":wins,"total":total})
                print(f"  {family:<10} {name:<20} Δ={delta:+7.2f}pp 60d={wins}/{total}")
        except Exception as exc:
            print(f"ERROR {asset}: {exc}")
    out={}
    if rows:
        v=pd.DataFrame(rows); print("\nHYPERLIQUID AGGREGATE")
        for family,name in best.items():
            c=v[v.family==family]; wins=int(c.wins.sum()); total=int(c.total.sum())
            out[family]={"name":name,"delta":float(c.delta.mean()),"positive":int((c.delta>0).sum()),"wins":wins,"total":total,"wpct":wins/total*100 if total else 0}
            print(f"{family:<10} {name:<20} meanΔ={c.delta.mean():+7.2f}pp assets+={(c.delta>0).sum()}/{len(c)} 60d={wins}/{total} ({wins/total*100 if total else 0:5.1f}%)")
    return out


def final_score(full,roll,best,hl):
    print("\n"+"="*120); print("FINAL NEW-SIGNAL SCORECARD"); print("="*120)
    rows=[]
    for family,name in best.items():
        s=stats(full,roll,name); h=hl.get(family,{})
        rows.append({"family":family,"name":name,"yd":s["delta"],"yr":s["wpct"],"dd":s["dd_delta"],"gb":s["gb_delta"],"hd":h.get("delta",np.nan),"hr":h.get("wpct",np.nan),"hp":h.get("positive",0)})
    score=pd.DataFrame(rows).sort_values(["hr","yr","hd","yd"],ascending=False)
    for i,(_,r) in enumerate(score.iterrows(),1):
        print(f"#{i} {r['family']:<10} {r['name']:<20} Yahoo Δ={r['yd']:+7.2f}pp roll={r['yr']:5.1f}% ΔDD={r['dd']:+6.2f}pp ΔGB={r['gb']:+6.2f}pp | HL Δ={r['hd']:+7.2f}pp roll={r['hr']:5.1f}% assets+={int(r['hp'])}/8")
    print("\nNo live files changed. Research-only screening completed.")


def main():
    print("="*120); print("ADDITIONAL EXIT SIGNAL SCREEN — SUPERTREND / CHOP / DONCHIAN / OBV")
    print("Research only | Intraday 1h | live bot unchanged | no keys | no orders")
    print("="*120)
    data=collect_yahoo(); full,roll=run_sweep(data)
    best=print_screen(full,roll); print_fee(full,best); asset_best(full,roll)
    hl=hl_validation(best); final_score(full,roll,best,hl)


if __name__ == "__main__":
    main()
