"""Research-only exit replay. No account keys, exchange orders, or live settings.

Input CSV columns: asset,side,entry_time,exit_time,entry_price,size,fees,funding,actual_net
Times: UTC ISO-8601. fees: total actual round-trip fees in USD.
funding: signed USD credit (+) / debit (-).
Uses completed 1m candle closes; stop fills are NOT guaranteed at candle close.
Usage: python research/profit_lock_replay.py trades.csv
"""
import csv
import datetime as dt
import sys
import time
import requests

API = "https://api.hyperliquid.xyz/info"
SLIPPAGE_BPS = 5.0
BUFFER_USD = 0.01
GIVEBACK_PCT = 0.30  # percentage points of entry notional
MIN_ARM_PCT = 0.20   # entry-notional percent

def timestamp(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()

def candles(coin, start, end):
    payload = {"type":"candleSnapshot","req":{"coin":coin,"interval":"1m",
               "startTime":int(start*1000),"endTime":int(end*1000)}}
    response = requests.post(API, json=payload, timeout=30)
    response.raise_for_status()
    return sorted(response.json(), key=lambda c: c["t"])

def replay(t):
    entry, end = timestamp(t["entry_time"]), timestamp(t["exit_time"])
    if end <= entry:
        raise ValueError("exit must be after entry")
    px, size = float(t["entry_price"]), abs(float(t["size"]))
    if px <= 0 or size <= 0:
        raise ValueError("invalid entry price or size")
    side = 1 if t["side"].lower() == "long" else -1
    fees, funding = float(t["fees"]), float(t["funding"])
    notional = px * size
    arm_usd = max(notional * MIN_ARM_PCT / 100, fees - funding + BUFFER_USD)
    observed_peak = float("-inf")
    armed = False
    data = candles(t["asset"], entry, end)
    # Closed candle after entry, before actual close. Exit uses next observed
    # close with conservative fixed slippage; no intrabar fill assumptions.
    for c in data:
        close_ms = int(c["T"])
        if close_ms <= entry * 1000 or close_ms >= end * 1000:
            continue
        mark = float(c["c"])
        unrealized = (mark - px) * size * side
        observed_peak = max(observed_peak, unrealized)
        if observed_peak >= arm_usd:
            armed = True
        if not armed:
            continue
        # Aim to retain fees + funding + buffer, while trailing from best close.
        floor = max(fees - funding + BUFFER_USD,
                    observed_peak - notional * GIVEBACK_PCT / 100)
        if unrealized <= floor:
            slipped = mark * (1 - side * SLIPPAGE_BPS / 10000)
            net = (slipped - px) * size * side - fees + funding
            return {"exit_time":dt.datetime.fromtimestamp(close_ms/1000,dt.timezone.utc).isoformat(),
                    "replay_net":net,"actual_net":float(t["actual_net"]),
                    "difference":net-float(t["actual_net"]),"triggered":True,
                    "armed":True,"candles":len(data)}
    return {"exit_time":None,"replay_net":float(t["actual_net"]),
            "actual_net":float(t["actual_net"]),"difference":0.0,
            "triggered":False,"armed":armed,"candles":len(data)}

def main():
    with open(sys.argv[1], newline="", encoding="utf-8") as f:
        trades = list(csv.DictReader(f))
    total_actual = total_replay = 0.0
    for i,t in enumerate(trades,1):
        try:
            r = replay(t)
            total_actual += r["actual_net"]
            total_replay += r["replay_net"]
            print(i,t["asset"],t["side"],r)
        except Exception as exc:
            print(i,t.get("asset"),"INCOMPLETE",str(exc))
        time.sleep(0.15)
    print("COMPARABLE TRADE TOTALS ONLY",{"actual":round(total_actual,6),
          "hypothetical":round(total_replay,6),
          "delta":round(total_replay-total_actual,6)})
    print("LIMITATIONS: 1m candle close sampling, fixed slippage, actual round-trip fees/funding assumed; "
          "no latency/order-book replay, partial fills, pyramids, or intrabar execution. "
          "Non-triggered trades retain actual outcome.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python research/profit_lock_replay.py trades.csv")
    main()
