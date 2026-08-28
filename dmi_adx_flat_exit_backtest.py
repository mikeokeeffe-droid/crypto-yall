"""
dmi_adx_flat_exit_backtest.py — full DMI + ADX FLAT-exit research.

RESEARCH ONLY. No live executor imports, no private keys, no order placement.

Tests DMI direction confirmation after the Intraday oscillator FLAT/zero-cross,
with and without ADX strength filters. ATR stops remain immediate. A pending
FLAT exit is cancelled if oscillator momentum recovers.

Coverage:
- 365-day Yahoo 1h fixed datasets
- fees 0.035%, 0.045%, 0.060% per side
- rolling 30/60/90/120-day robustness
- older/newer half consistency
- coin-by-coin and BTC/ETH long-vs-short diagnostics
- recent Hyperliquid 1h validation (~4,900 bars)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import rsi_exit_12m_backtest as research
from intraday_data_loader import fetch_candles

PERIOD = 14
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
    min_spread: float = 0.0
    adx_max: float | None = None
    require_cross: bool = False
    require_adx_falling: bool = False
    scope: str = "all"


RULES = [
    Rule("BASELINE"),
    Rule("DMI ADVERSE"),
    Rule("DMI SPREAD 5", min_spread=5.0),
    Rule("DMI SPREAD 10", min_spread=10.0),
    Rule("DMI CROSS", require_cross=True),
    Rule("DMI + ADX<20", adx_max=20.0),
    Rule("DMI + ADX<25", adx_max=25.0),
    Rule("DMI + ADX<30", adx_max=30.0),
    Rule("DMI5 + ADX<20", min_spread=5.0, adx_max=20.0),
    Rule("DMI5 + ADX<25", min_spread=5.0, adx_max=25.0),
    Rule("DMI5 + ADX<30", min_spread=5.0, adx_max=30.0),
    Rule("DMI10 + ADX<20", min_spread=10.0, adx_max=20.0),
    Rule("DMI10 + ADX<25", min_spread=10.0, adx_max=25.0),
    Rule("DMI10 + ADX<30", min_spread=10.0, adx_max=30.0),
    Rule("DMI + ADX FALL", require_adx_falling=True),
    Rule("DMI5 + ADX FALL", min_spread=5.0, require_adx_falling=True),
]
RULE_MAP = {r.name: r for r in RULES}


def dmi_wilder(df: pd.DataFrame, period: int = PERIOD) -> pd.DataFrame:
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)

    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)

    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(
        np.where((up > down) & (up > 0), up, 0.0), index=df.index, dtype=float
    )
    minus_dm = pd.Series(
        np.where((down > up) & (down > 0), down, 0.0), index=df.index, dtype=float
    )

    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_sm = plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    minus_sm = minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100.0 * plus_sm / atr.replace(0, np.nan)
    minus_di = 100.0 * minus_sm / atr.replace(0, np.nan)
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return pd.DataFrame({"PLUS_DI": plus_di, "MINUS_DI": minus_di, "ADX": adx})


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = research.prepare_indicators(df)
    dmi = dmi_wilder(out)
    out[["PLUS_DI", "MINUS_DI", "ADX"]] = dmi[["PLUS_DI", "MINUS_DI", "ADX"]]
    return out


def trade_return(side: int, entry: float, exit_: float) -> float:
    return exit_ / entry - 1.0 if side == 1 else entry / exit_ - 1.0


def adverse_margin(side: int, plus_di: float, minus_di: float) -> float:
    return (minus_di - plus_di) if side == 1 else (plus_di - minus_di)


def adverse_cross(side: int, plus: np.ndarray, minus: np.ndarray, i: int) -> bool:
    if i < 1 or np.isnan([plus[i - 1], minus[i - 1], plus[i], minus[i]]).any():
        return False
    prev = adverse_margin(side, plus[i - 1], minus[i - 1])
    curr = adverse_margin(side, plus[i], minus[i])
    return prev <= 0 < curr


def confirms(rule: Rule, side: int, plus: np.ndarray, minus: np.ndarray, adx: np.ndarray, i: int) -> bool:
    if rule.name == "BASELINE":
        return True
    if rule.scope == "long" and side == -1:
        return True
    if rule.scope == "short" and side == 1:
        return True
    if np.isnan([plus[i], minus[i], adx[i]]).any():
        return False

    margin = adverse_margin(side, plus[i], minus[i])
    if margin <= rule.min_spread:
        return False
    if rule.require_cross and not adverse_cross(side, plus, minus, i):
        return False
    if rule.adx_max is not None and not (adx[i] < rule.adx_max):
        return False
    if rule.require_adx_falling:
        if i < 1 or np.isnan(adx[i - 1]) or not (adx[i] < adx[i - 1]):
            return False
    return True


def simulate(df: pd.DataFrame, allow_short: bool, rule: Rule, fee: float):
    idx = df.index
    close = df["Close"].to_numpy(float)
    osc = df["TwoPole_Osc"].to_numpy(float)
    atr = df["ATR"].to_numpy(float)
    plus = df["PLUS_DI"].to_numpy(float)
    minus = df["MINUS_DI"].to_numpy(float)
    adx = df["ADX"].to_numpy(float)

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
        prev_osc, curr_osc = osc[i - 1], osc[i]
        atr_now = atr[i] if not np.isnan(atr[i]) else 0.0

        if side != 0:
            peak_return = max(peak_return, trade_return(side, entry_price, price))

        hard_exit = False
        if side == 1 and not np.isnan(entry_price):
            hard_exit = atr_now > 0 and price <= entry_price - research.ATR_STOP_MULT * atr_now
        elif side == -1 and not np.isnan(entry_price):
            hard_exit = atr_now > 0 and price >= entry_price + research.ATR_STOP_MULT * atr_now

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

        confirmed = side != 0 and pending_flat and confirms(rule, side, plus, minus, adx, i)
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
                    exit_reason="ATR stop" if hard_exit else f"flat + {rule.name}",
                    bars_held=i - entry_i,
                )
            )
            fee_events[i] += fee
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
            position[i] = 1
            fee_events[i] += fee
            continue
        if allow_short and prev_osc >= research.OSC_UPPER > curr_osc:
            side = -1
            entry_price = price
            entry_i = i
            position[i] = -1
            fee_events[i] += fee

    pos = pd.Series(position, index=idx, dtype=float)
    gross_returns = pos.shift(1).fillna(0.0) * df["Close"].pct_change().fillna(0.0)
    returns = gross_returns - pd.Series(fee_events, index=idx)
    return returns, trades


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


def fetch_fixed_yahoo() -> dict[str, pd.DataFrame]:
    data = {}
    print("\nFIXED YAHOO DATASETS")
    for asset in ASSETS:
        df = trim_year(prepare(research.fetch_yahoo_1h(asset)))
        data[asset] = df
        fp = pd.util.hash_pandas_object(df[["Open", "High", "Low", "Close", "Volume"]], index=True).sum()
        print(f"{asset:<13} bars={len(df):4d} {df.index.min()} -> {df.index.max()} hash={int(fp)&0xffffffffffffffff:016x}")
    return data


def collect(data: dict[str, pd.DataFrame]):
    full, roll, halves = [], [], []
    for asset, df in data.items():
        allow_short = bool(research.get_asset_profile(asset)["allow_short"])
        mid = df.index.min() + (df.index.max() - df.index.min()) / 2
        for fee in FEES:
            for rule in RULES:
                ret, trades = simulate(df, allow_short, rule, fee)
                full.append({"asset": asset, "fee": fee, "variant": rule.name, **research.metrics(ret, trades)})
                for label, start, end in [
                    ("OLDER", df.index.min(), mid),
                    ("NEWER", mid, df.index.max() + pd.Timedelta(hours=1)),
                ]:
                    pr = ret[(ret.index >= start) & (ret.index < end)]
                    pt = [t for t in trades if start <= t.exit_time < end]
                    halves.append({"asset": asset, "fee": fee, "variant": rule.name, "half": label, **research.metrics(pr, pt)})
                for days, step in WINDOWS:
                    for name, start, end in windows(df.index, days, step):
                        wr = ret[(ret.index >= start) & (ret.index < end)]
                        wt = [t for t in trades if start <= t.exit_time < end]
                        roll.append({"asset": asset, "fee": fee, "variant": rule.name, "window_days": days, "window": name, **research.metrics(wr, wt)})
    return pd.DataFrame(full), pd.DataFrame(roll), pd.DataFrame(halves)


def global_ranking(full: pd.DataFrame, roll: pd.DataFrame) -> list[str]:
    nf = full[full.fee == NORMAL_FEE]
    nr = roll[roll.fee == NORMAL_FEE]
    base = nf[nf.variant == "BASELINE"]
    base_ret = base.return_pct.mean()
    base_dd = base.max_dd_pct.mean()
    base_gb = base.avg_giveback_pct.mean()

    rows = []
    for rule in RULES[1:]:
        c = nf[nf.variant == rule.name]
        p = nr[nr.variant.isin(["BASELINE", rule.name])].pivot_table(
            index=["asset", "window_days", "window"], columns="variant", values="return_pct", aggfunc="first"
        ).dropna()
        delta = p[rule.name] - p["BASELINE"]
        rows.append({
            "variant": rule.name,
            "ret": c.return_pct.mean(),
            "dret": c.return_pct.mean() - base_ret,
            "dd": c.max_dd_pct.mean(),
            "ddd": c.max_dd_pct.mean() - base_dd,
            "gb": c.avg_giveback_pct.mean(),
            "dgb": c.avg_giveback_pct.mean() - base_gb,
            "wins": int((delta > 0).sum()),
            "total": len(delta),
            "wpct": float((delta > 0).mean() * 100),
            "avgd": float(delta.mean()),
            "medd": float(delta.median()),
            "worst": float(delta.min()),
        })
    rank = pd.DataFrame(rows).sort_values(["wpct", "avgd", "dret"], ascending=False)

    print("\n" + "=" * 118)
    print("GLOBAL DMI + ADX RANKING — NORMAL FEE")
    print("=" * 118)
    print(f"BASELINE return={base_ret:+.2f}% DD={base_dd:+.2f}% giveback={base_gb:.3f}%")
    print(f"{'RULE':<20} {'RET':>8} {'ΔRET':>8} {'DD':>8} {'ΔDD':>8} {'GB':>7} {'ROLL':>11} {'AVGΔ':>8} {'WORST':>8}")
    for _, r in rank.iterrows():
        print(f"{r.variant:<20} {r.ret:+8.2f} {r.dret:+8.2f} {r.dd:+8.2f} {r.ddd:+8.2f} {r.gb:7.3f} {int(r.wins):3d}/{int(r.total):<3d} {r.avgd:+8.2f} {r.worst:+8.2f}")

    gates = rank[(rank.dret > 0) & (rank.wpct >= 55) & (rank.ddd >= -1.5) & (rank.dgb <= 0.75)]
    print("\nBROAD ROBUSTNESS GATE")
    if gates.empty:
        print("No universal DMI + ADX rule passed every broad gate.")
    else:
        for _, r in gates.iterrows():
            print(f"PASS {r.variant}: Δreturn={r.dret:+.2f}pp rolling={r.wpct:.1f}% ΔDD={r.ddd:+.2f}pp ΔGB={r.dgb:+.3f}pp")
    return rank.variant.head(6).tolist()


def fee_sensitivity(full: pd.DataFrame, top: list[str]) -> None:
    print("\n" + "=" * 118)
    print("FEE SENSITIVITY")
    print("=" * 118)
    for fee in FEES:
        f = full[full.fee == fee]
        b = f[f.variant == "BASELINE"].return_pct.mean()
        print(f"\nFee={fee*100:.3f}%/side baseline={b:+.2f}%")
        for name in top:
            v = f[f.variant == name].return_pct.mean()
            print(f"  {name:<20} return={v:+7.2f}% Δ={v-b:+7.2f}pp")


def rolling_detail(roll: pd.DataFrame, top: list[str]) -> None:
    print("\n" + "=" * 118)
    print("ROLLING ROBUSTNESS BY WINDOW — NORMAL FEE")
    print("=" * 118)
    r = roll[roll.fee == NORMAL_FEE]
    for name in top:
        print(f"\n{name}")
        for days, _ in WINDOWS:
            p = r[(r.window_days == days) & (r.variant.isin(["BASELINE", name]))].pivot_table(
                index=["asset", "window"], columns="variant", values="return_pct", aggfunc="first"
            ).dropna()
            d = p[name] - p["BASELINE"]
            print(f"  {days:3d}d {int((d>0).sum()):3d}/{len(d):<3d} ({(d>0).mean()*100:5.1f}%) avg={d.mean():+6.2f}pp median={d.median():+6.2f}pp worst={d.min():+6.2f}pp")


def asset_best(full: pd.DataFrame, roll: pd.DataFrame, halves: pd.DataFrame) -> dict[str, str]:
    nf = full[full.fee == NORMAL_FEE]
    hf = full[full.fee == max(FEES)]
    nr = roll[roll.fee == NORMAL_FEE]
    nh = halves[halves.fee == NORMAL_FEE]
    selected = {}
    print("\n" + "=" * 118)
    print("BEST DMI + ADX RULE PER ASSET")
    print("=" * 118)
    for asset in ASSETS:
        b = nf[(nf.asset == asset) & (nf.variant == "BASELINE")].iloc[0]
        bh = hf[(hf.asset == asset) & (hf.variant == "BASELINE")].iloc[0]
        newer_b = nh[(nh.asset == asset) & (nh.variant == "BASELINE") & (nh.half == "NEWER")].iloc[0]
        rows = []
        for rule in RULES[1:]:
            c = nf[(nf.asset == asset) & (nf.variant == rule.name)].iloc[0]
            ch = hf[(hf.asset == asset) & (hf.variant == rule.name)].iloc[0]
            newer = nh[(nh.asset == asset) & (nh.variant == rule.name) & (nh.half == "NEWER")].iloc[0]
            p = nr[(nr.asset == asset) & (nr.window_days.isin([60,90,120])) & (nr.variant.isin(["BASELINE", rule.name]))].pivot_table(
                index=["window_days", "window"], columns="variant", values="return_pct", aggfunc="first"
            ).dropna()
            d = p[rule.name] - p["BASELINE"]
            rows.append({"name":rule.name,"dret":c.return_pct-b.return_pct,"hd":ch.return_pct-bh.return_pct,"wpct":(d>0).mean()*100,"avgd":d.mean(),"ddd":c.max_dd_pct-b.max_dd_pct,"dgb":c.avg_giveback_pct-b.avg_giveback_pct,"newer":newer.return_pct-newer_b.return_pct})
        rr = pd.DataFrame(rows).sort_values(["wpct","avgd","dret"], ascending=False).iloc[0]
        selected[asset] = rr["name"]
        strong = rr.dret>0 and rr.hd>0 and rr.wpct>=65 and rr.ddd>=-3
        print(f"{asset:<13} {'STRONG' if strong else 'MIXED':<6} {rr['name']:<20} Δ12m={rr.dret:+7.2f}pp highFee={rr.hd:+7.2f}pp roll={rr.wpct:5.1f}% avg={rr.avgd:+6.2f}pp ΔDD={rr.ddd:+6.2f}pp ΔGB={rr.dgb:+6.2f}pp newer={rr.newer:+6.2f}pp")
    return selected


def side_diagnostics(data: dict[str, pd.DataFrame], top: list[str]) -> None:
    print("\n" + "=" * 118)
    print("BTC / ETH LONG-SHORT DIAGNOSTICS — NORMAL FEE")
    print("=" * 118)
    for asset in ["BTC-USD", "ETH-USD"]:
        df = data[asset]
        base_ret, base_trades = simulate(df, True, RULE_MAP["BASELINE"], NORMAL_FEE)
        bm = research.metrics(base_ret, base_trades)
        print(f"\n{asset} baseline={bm['return_pct']:+.2f}%")
        for name in top[:4]:
            base_rule = RULE_MAP[name]
            for scope in ["long", "short"]:
                rule = Rule(name + " " + scope.upper(), base_rule.min_spread, base_rule.adx_max, base_rule.require_cross, base_rule.require_adx_falling, scope)
                ret, trades = simulate(df, True, rule, NORMAL_FEE)
                m = research.metrics(ret, trades)
                side = 1 if scope == "long" else -1
                ts = [t for t in trades if t.side == side]
                comp = (np.prod([1+t.net_return for t in ts])-1)*100 if ts else 0
                print(f"  {name:<18} {scope:<5} return={m['return_pct']:+7.2f}% Δ={m['return_pct']-bm['return_pct']:+6.2f}pp n={len(ts):3d} sideCompound={comp:+7.2f}%")


def half_consistency(halves: pd.DataFrame, top: list[str]) -> None:
    print("\n" + "=" * 118)
    print("OLDER / NEWER HALF — NORMAL FEE, MEAN ACROSS ASSETS")
    print("=" * 118)
    h = halves[halves.fee == NORMAL_FEE]
    for name in ["BASELINE"] + top:
        c = h[h.variant == name]
        print(f"{name:<20} older={c[c.half=='OLDER'].return_pct.mean():+8.2f}% newer={c[c.half=='NEWER'].return_pct.mean():+8.2f}%")


def hyperliquid_validation(top: list[str]) -> None:
    names = []
    for n in top + ["DMI ADVERSE", "DMI + ADX<20", "DMI + ADX<25", "DMI + ADX<30"]:
        if n in RULE_MAP and n not in names:
            names.append(n)
    names = names[:7]
    rows = []
    print("\n" + "=" * 118)
    print("HYPERLIQUID RECENT VALIDATION — NORMAL FEE")
    print("=" * 118)
    print("Candidates:", ", ".join(names))
    for asset in ASSETS:
        try:
            df = prepare(fetch_candles(asset, interval="1h", lookback_hours=HL_LOOKBACK_HOURS))
            allow_short = bool(research.get_asset_profile(asset)["allow_short"])
            br, bt = simulate(df, allow_short, RULE_MAP["BASELINE"], NORMAL_FEE)
            bm = research.metrics(br, bt)
            print(f"\n{asset:<13} bars={len(df):4d} baseline={bm['return_pct']:+7.2f}%")
            for name in names:
                rr, tt = simulate(df, allow_short, RULE_MAP[name], NORMAL_FEE)
                m = research.metrics(rr, tt)
                wins = total = 0
                for _, start, end in windows(df.index, 60, 30):
                    bwr = br[(br.index>=start)&(br.index<end)]
                    rwr = rr[(rr.index>=start)&(rr.index<end)]
                    bwm = research.metrics(bwr, [t for t in bt if start<=t.exit_time<end])
                    rwm = research.metrics(rwr, [t for t in tt if start<=t.exit_time<end])
                    if bwm and rwm:
                        wins += int(rwm['return_pct'] > bwm['return_pct'])
                        total += 1
                delta = m['return_pct'] - bm['return_pct']
                rows.append({"asset":asset,"variant":name,"delta":delta,"wins":wins,"total":total})
                print(f"  {name:<20} return={m['return_pct']:+7.2f}% Δ={delta:+7.2f}pp 60d={wins}/{total}")
        except Exception as exc:
            print(f"ERROR {asset}: {exc}")
    if rows:
        v = pd.DataFrame(rows)
        print("\nHYPERLIQUID AGGREGATE")
        for name in names:
            c=v[v.variant==name]
            wins,total=int(c.wins.sum()),int(c.total.sum())
            print(f"{name:<20} meanΔ={c.delta.mean():+7.2f}pp positiveAssets={(c.delta>0).sum()}/{len(c)} 60d={wins}/{total} ({wins/total*100 if total else 0:5.1f}%)")


def main() -> None:
    print("=" * 118)
    print("FULL DMI + ADX FLAT-EXIT TEST — INTRADAY 1H")
    print("Research only | Live bot unchanged | No keys | No orders")
    print(f"Rules={len(RULES)} | Yahoo={research.TEST_DAYS}d | Hyperliquid recent={HL_LOOKBACK_HOURS}h | Fees={FEES}")
    print("=" * 118)
    data = fetch_fixed_yahoo()
    full, roll, halves = collect(data)
    top = global_ranking(full, roll)
    fee_sensitivity(full, top)
    rolling_detail(roll, top)
    selected = asset_best(full, roll, halves)
    side_diagnostics(data, top)
    half_consistency(halves, top)
    hyperliquid_validation(top)
    print("\nFINAL ASSET PICKS (RESEARCH ONLY)")
    for asset, rule in selected.items():
        print(f"  {asset:<13} {rule}")
    print("Live strategy files were not changed.")


if __name__ == "__main__":
    main()
