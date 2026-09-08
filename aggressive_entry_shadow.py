"""Observation-only entry-quality scoring for the Aggressive bot.

This module never blocks, opens, closes, or resizes a trade. It only produces
diagnostic fields that are attached to Aggressive entry records so later
performance can be compared by entry quality and entry type.
"""

import math
import numpy as np
import pandas as pd


def _wilder_adx(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)

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

    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_smoothed = plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    minus_smoothed = minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    plus_di = 100.0 * plus_smoothed / atr.replace(0, np.nan)
    minus_di = 100.0 * minus_smoothed / atr.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return adx, plus_di, minus_di


def _rolling_vwap_dev(df: pd.DataFrame, period: int = 20) -> pd.Series:
    typical = (df["High"] + df["Low"] + df["Close"]) / 3.0
    volume = df["Volume"].astype(float)
    roll_value = (typical * volume).rolling(period, min_periods=period).sum()
    roll_volume = volume.rolling(period, min_periods=period).sum()
    vwap = roll_value / roll_volume.replace(0, np.nan)
    return (df["Close"] - vwap) / df["Close"].replace(0, np.nan)


def score_entry_quality(
    df: pd.DataFrame,
    signal_df: pd.DataFrame,
    side: str,
    entry_type: str,
) -> dict:
    """Return an observation-only quality score and diagnostics.

    Score is 0-100. STRONG >= 70, MEDIUM >= 50, otherwise WEAK.
    It intentionally uses only current/past closed bars.
    """
    if df is None or signal_df is None or len(df) < 30 or len(signal_df) < 2:
        return {
            "entry_quality": "UNKNOWN",
            "entry_quality_score": 0.0,
            "entry_type": entry_type,
        }

    adx_s, plus_di_s, minus_di_s = _wilder_adx(df)
    vwap_dev_s = _rolling_vwap_dev(df)

    close = float(df["Close"].iloc[-1])
    atr = float(signal_df["ATR"].iloc[-1]) if "ATR" in signal_df.columns else 0.0
    atr_pct = (atr / close * 100.0) if close > 0 and math.isfinite(atr) else 0.0

    osc = float(signal_df["TwoPole_Osc"].iloc[-1]) if "TwoPole_Osc" in signal_df.columns else 0.0
    prev_osc = float(signal_df["TwoPole_Osc"].iloc[-2]) if "TwoPole_Osc" in signal_df.columns else osc
    osc_delta = osc - prev_osc

    adx = float(adx_s.iloc[-1]) if pd.notna(adx_s.iloc[-1]) else 0.0
    plus_di = float(plus_di_s.iloc[-1]) if pd.notna(plus_di_s.iloc[-1]) else 0.0
    minus_di = float(minus_di_s.iloc[-1]) if pd.notna(minus_di_s.iloc[-1]) else 0.0
    vwap_dev = float(vwap_dev_s.iloc[-1]) if pd.notna(vwap_dev_s.iloc[-1]) else 0.0

    is_long = side == "long"
    directional_ok = plus_di > minus_di if is_long else minus_di > plus_di
    vwap_ok = vwap_dev >= 0 if is_long else vwap_dev <= 0
    oscillator_ok = osc_delta > 0 if is_long else osc_delta < 0

    score = 0.0

    # Trend strength: 0-30 points.
    if adx >= 30:
        score += 30
    elif adx >= 25:
        score += 25
    elif adx >= 20:
        score += 18
    elif adx >= 15:
        score += 10

    # Directional confirmation: 25 points.
    if directional_ok:
        score += 25

    # VWAP alignment: 15 points.
    if vwap_ok:
        score += 15

    # Oscillator moving in trade direction: 20 points.
    if oscillator_ok:
        score += 20

    # Volatility sanity: 10 points for a tradable but not extreme range.
    if 0.25 <= atr_pct <= 4.0:
        score += 10
    elif 0.10 <= atr_pct <= 6.0:
        score += 5

    # Sync entries are deliberately marked down slightly because they join an
    # already-running signal and are the main behaviour we want to study.
    if entry_type.startswith("sync_"):
        score = max(0.0, score - 10.0)

    quality = "STRONG" if score >= 70 else "MEDIUM" if score >= 50 else "WEAK"

    return {
        "entry_quality": quality,
        "entry_quality_score": round(score, 1),
        "entry_type": entry_type,
        "entry_adx": round(adx, 2),
        "entry_plus_di": round(plus_di, 2),
        "entry_minus_di": round(minus_di, 2),
        "entry_atr_pct": round(atr_pct, 3),
        "entry_vwap_dev_pct": round(vwap_dev * 100.0, 3),
        "entry_osc": round(osc, 4),
        "entry_osc_delta": round(osc_delta, 4),
        "entry_directional_ok": bool(directional_ok),
        "entry_vwap_ok": bool(vwap_ok),
        "entry_oscillator_ok": bool(oscillator_ok),
        "entry_shadow_only": True,
    }
