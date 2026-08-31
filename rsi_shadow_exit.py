"""Read-only RSI reversal shadow helpers.

Research rule only; this module never places orders.
Long: arm when RSI(14) >= 70, hypothetical exit after RSI falls back below 70.
Short: arm when RSI(14) <= 30, hypothetical exit after RSI rises back above 30.
"""

import numpy as np
import pandas as pd

RSI_PERIOD = 14
RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0


def rsi_wilder(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    close = close.astype(float)
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_loss != 0, 100.0)
    rsi = rsi.where(avg_gain != 0, 0.0)
    return rsi


def rsi_reversal_shadow(df: pd.DataFrame, side: str, was_armed: bool = False):
    rsi = rsi_wilder(df["Close"])
    current = float(rsi.iloc[-1]) if len(rsi) and np.isfinite(rsi.iloc[-1]) else None
    previous = float(rsi.iloc[-2]) if len(rsi) >= 2 and np.isfinite(rsi.iloc[-2]) else None
    if current is None:
        return "N/A", was_armed, None

    armed = bool(was_armed)
    decision = "HOLD"
    if side == "long":
        if current >= RSI_OVERBOUGHT:
            armed = True
        if armed and previous is not None and previous >= RSI_OVERBOUGHT and current < RSI_OVERBOUGHT:
            decision = "EXIT"
    else:
        if current <= RSI_OVERSOLD:
            armed = True
        if armed and previous is not None and previous <= RSI_OVERSOLD and current > RSI_OVERSOLD:
            decision = "EXIT"
    return decision, armed, current
