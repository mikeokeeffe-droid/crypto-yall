"""Offline synthetic paper demo for the two existing strategy signal generators.

No executors, trading credentials, price downloads, real orders or network.
This deterministic smoke test is NOT a historical backtest or a live trading bot.
"""
import socket
def _deny_network(*_args, **_kwargs):
    raise RuntimeError("NETWORK DISABLED: synthetic paper demo")
socket.socket = _deny_network
socket.create_connection = _deny_network

import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aggressive_strategy import generate_aggressive_signals
from intraday_strategy import generate_intraday_signals

START_BALANCE = 100.0
POSITION_FRACTION = 0.10

def synthetic_candles(freq: str, seed: int) -> pd.DataFrame:
    """Deterministic fabricated OHLCV; never market prices."""
    n = 600
    rng = np.random.default_rng(seed)
    step = np.arange(n)
    closes = 100 + 10 * np.sin(step / 10) + 5 * np.sin(step / 31) + rng.normal(0, 0.8, n)
    opens = np.r_[closes[0], closes[:-1]]
    highs = np.maximum(opens, closes) + 0.6
    lows = np.minimum(opens, closes) - 0.6
    index = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes,
                         "Volume": np.full(n, 1000.0)}, index=index)

def run_paper_ledger(candles: pd.DataFrame, signals: pd.Series) -> tuple[float, list[tuple]]:
    """Apply signals only at the following bar's open; fake PnL only."""
    cash = START_BALANCE
    units = 0.0
    entry_price = 0.0
    trades = []
    for i in range(1, len(candles)):
        target = int(signals.iloc[i - 1])
        if target not in (-1, 0, 1):
            raise ValueError("Unsupported signal")
        side = (units > 0) - (units < 0)
        if target == side:
            continue
        fill = float(candles["Open"].iloc[i])
        if not (np.isfinite(fill) and fill > 0):
            raise ValueError("Invalid virtual fill price")
        if units:
            pnl = units * (fill - entry_price)
            cash += units * fill
            trades.append(("CLOSE", str(candles.index[i]), round(pnl, 4)))
            units = 0.0
        if target:
            units = target * (START_BALANCE * POSITION_FRACTION) / fill
            entry_price = fill
            cash -= units * fill
            trades.append(("LONG" if target == 1 else "SHORT", str(candles.index[i]), round(fill, 4)))
    return cash + units * float(candles["Close"].iloc[-1]), trades

def main() -> None:
    for name, freq, seed, generator in (
        ("INTRADAY 1H", "1h", 19, generate_intraday_signals),
        ("AGGRESSIVE 30M", "30min", 23, generate_aggressive_signals),
    ):
        candles = synthetic_candles(freq, seed)
        decisions = generator(candles, allow_short=True)
        equity, trades = run_paper_ledger(candles, decisions["Signal"])
        print(f"{name}: fake start {START_BALANCE:.2f} USD, fake end {equity:.2f} USD; "
              f"{len(trades)} simulated order events")
        for event in trades[:8]:
            print("  ", *event)
        if len(trades) > 8:
            print(f"   ... {len(trades) - 8} more simulated events")
    print("SYNTHETIC OFFLINE DEMO ONLY: no price feed, keys, network or actual orders")

if __name__ == "__main__":
    main()
