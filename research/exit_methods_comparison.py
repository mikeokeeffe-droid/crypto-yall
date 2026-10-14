"""Research-only three-way exit comparison. NO TRADING KEYS OR ORDERS.
Usage: python research/exit_methods_comparison.py trades.csv
Required CSV: asset,side,entry_time,exit_time,entry_price,size,fees,funding,actual_net
UTC timestamps. Models use COMPLETED 1m candle CLOSES, not executable stop fills.
Exchange-side is a proxy with 1m resolution, not a tick-level or mark-price replay.
Actual baseline is recorded actual_net (not a simulated 5-minute executor).
"""
import csv
import datetime as dt
import sys
import requests

URL = "https://api.hyperliquid.xyz/info"
ARM_PCT = 0.20
TRAIL_PP = 0.30
BUFFER_USD = 0.01
SLIPPAGE_BPS = 5.0

def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000

def market_bars(t):
    start, end = int(ts(t["entry_time"])), int(ts(t["exit_time"]))
    if end <= start:
        raise ValueError("Exit must be after entry")
    payload = {"type":"candleSnapshot","req":{"coin":t["asset"],"interval":"1m",
                "startTime":start,"endTime":end}}
    r = requests.post(URL, json=payload, timeout=30)
    r.raise_for_status()
    bars = sorted(r.json(), key=lambda b:int(b["t"]))
    if not isinstance(bars,list) or not bars:
        raise ValueError("No candles returned")
    # Incomplete coverage must not be reported as a completed test.
    if int(bars[0]["t"]) > start + 60000 or int(bars[-1]["T"]) < end - 120000:
        raise ValueError("Incomplete candle coverage; 5000-candle history cap may apply")
    return [b for b in bars if start < int(b["T"]) < end]

def evaluate(t,bars,partial=False):
    price, size = float(t["entry_price"]), abs(float(t["size"]))
    if price <= 0 or size <= 0: raise ValueError("Invalid price/size")
    side = 1 if t["side"].lower() == "long" else -1
    if t["side"].lower() not in ("long","short"): raise ValueError("Invalid side")
    fees, funding = float(t["fees"]), float(t["funding"])
    notional = price*size
    arm = max(notional*ARM_PCT/100, fees-funding+BUFFER_USD)
    peak, armed = 0.0, False
    remaining, realized, exits = 1.0, 0.0, []
    for b in bars:
        close = float(b["c"])
        pnl = (close-price)*size*side
        peak = max(peak,pnl)
        if peak >= arm: armed = True
        if not armed: continue
        # Partial variant takes half when the profit arm is reached, then trails remainder.
        if partial and remaining == 1.0:
            slipped = close*(1-side*SLIPPAGE_BPS/10000)
            realized += (slipped-price)*size*side*0.5
            remaining = 0.5
            exits.append("half")
        floor = max(fees-funding+BUFFER_USD, peak-notional*TRAIL_PP/100)
        if pnl <= floor:
            slipped = close*(1-side*SLIPPAGE_BPS/10000)
            realized += (slipped-price)*size*side*remaining
            exits.append("trail")
            remaining = 0
            break
    if remaining:
        # If no full exit, model remaining fraction using actual net grossed up
        # by actual fees/funding, then allocate total fees/funding once.
        actual_gross = float(t["actual_net"])+fees-funding
        realized += remaining*actual_gross
    # Fees are actual round-trip total, not incremental partial-exit fee estimate.
    # Thus partial case may underestimate fees; sensitivity analysis needed.
    return realized-fees+funding, "+".join(exits) if exits else "actual_exit"

def main(path):
    totals = {"actual":0.0,"trail_1m_proxy":0.0,"half_then_trail":0.0}
    count = 0
    with open(path,newline="",encoding="utf8") as f:
        for t in csv.DictReader(f):
            try:
                bars = market_bars(t)
                if not bars: raise ValueError("No completed bars inside trade")
                actual = float(t["actual_net"])
                trail, reason = evaluate(t,bars)
                half, half_reason = evaluate(t,bars,partial=True)
                for k,v in (("actual",actual),("trail_1m_proxy",trail),("half_then_trail",half)):
                    totals[k]+=v
                count+=1
                print(t["asset"],"actual",round(actual,5),"trail",round(trail,5),reason,
                      "half",round(half,5),half_reason)
            except Exception as e:
                print(t.get("asset","?"),"SKIPPED",str(e))
    print("COMPARABLE TRADES",count)
    print("TOTAL NET USD (approximate; see limitations)",{k:round(v,5) for k,v in totals.items()})
    print("LIMITATIONS: 1m candle-close proxies do NOT model exchange stop trigger/fill,"
          " mark-price vs last-price differences, latency, intrabar moves, partial fills,"
          " order rejection, pyramiding, or actual incremental partial-exit fees."
          " Actual baseline is historical recorded net, not a synthetic five-minute strategy."
          " Treat this as a screening test, NOT a validated profit improvement.")

if __name__ == "__main__":
    if len(sys.argv)!=2: raise SystemExit("Usage: python research/exit_methods_comparison.py trades.csv")
    main(sys.argv[1])
