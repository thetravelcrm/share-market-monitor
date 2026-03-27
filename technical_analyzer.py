# ─────────────────────────────────────────────────────────────
#  technical_analyzer.py  –  RSI, SMA, Bollinger, Support/Resistance
#  All calculations use only pandas — no extra packages needed.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import numpy as np


@dataclass
class TechnicalData:
    rsi_14: float          # 0–100  (< 35 oversold, > 65 overbought)
    sma_20: float          # 20-day simple moving average
    sma_50: float          # 50-day simple moving average (0 if not enough data)
    trend: str             # "Uptrend" | "Downtrend" | "Sideways"
    support: float         # strongest recent support level
    resistance: float      # strongest recent resistance level
    near_support: bool     # current price within 2% above support
    near_resistance: bool  # current price within 2% below resistance
    bb_pct: float          # Bollinger Band %B  (0 = lower band, 1 = upper band)
    bb_squeeze: bool       # True when bands are tight (< 2% of price)


def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.rolling(period, min_periods=period).mean().iloc[-1]
    avg_loss = loss.rolling(period, min_periods=period).mean().iloc[-1]
    if pd.isna(avg_gain) or pd.isna(avg_loss):
        return 50.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def _bollinger(close: pd.Series, period: int = 20) -> tuple[float, float, float]:
    """Return (lower_band, upper_band, %B) based on last `period` closes."""
    if len(close) < period:
        c = float(close.iloc[-1])
        return c, c, 0.5
    sma  = close.rolling(period).mean().iloc[-1]
    std  = close.rolling(period).std().iloc[-1]
    upper = sma + 2 * std
    lower = sma - 2 * std
    cur   = float(close.iloc[-1])
    bb_pct = (cur - lower) / (upper - lower) if (upper - lower) > 0 else 0.5
    return round(lower, 2), round(upper, 2), round(bb_pct, 3)


def _find_support_resistance(
    lows: pd.Series, highs: pd.Series, current_price: float, lookback: int = 20
) -> tuple[float, float]:
    """
    Support  = strongest low cluster in last `lookback` bars.
    Resistance = strongest high cluster in last `lookback` bars.
    Uses a simple pivot approach: find local min/max with a 3-bar window.
    """
    recent_lows  = lows.iloc[-lookback:]
    recent_highs = highs.iloc[-lookback:]

    # pivot lows — local minimum in a 3-bar window
    pivot_lows  = [recent_lows.iloc[i] for i in range(1, len(recent_lows) - 1)
                   if recent_lows.iloc[i] <= recent_lows.iloc[i-1]
                   and recent_lows.iloc[i] <= recent_lows.iloc[i+1]]
    # pivot highs
    pivot_highs = [recent_highs.iloc[i] for i in range(1, len(recent_highs) - 1)
                   if recent_highs.iloc[i] >= recent_highs.iloc[i-1]
                   and recent_highs.iloc[i] >= recent_highs.iloc[i+1]]

    support    = min(pivot_lows)  if pivot_lows  else float(recent_lows.min())
    resistance = max(pivot_highs) if pivot_highs else float(recent_highs.max())

    # Ensure support < price < resistance (sanity check)
    if support >= current_price:
        support = float(recent_lows.min())
    if resistance <= current_price:
        resistance = float(recent_highs.max())

    return round(support, 2), round(resistance, 2)


def compute_technicals(hist: pd.DataFrame, current_price: float) -> Optional[TechnicalData]:
    """
    Compute all technical indicators from a yfinance history DataFrame.
    `hist` must have columns: Close, High, Low with a DatetimeIndex.
    Returns None if there is insufficient data.
    """
    try:
        if hist is None or hist.empty or len(hist) < 15:
            return None

        close = hist["Close"].dropna()
        high  = hist["High"].dropna()
        low   = hist["Low"].dropna()

        if len(close) < 15:
            return None

        # ── RSI ────────────────────────────────────────────────
        rsi = _rsi(close)

        # ── SMA ────────────────────────────────────────────────
        sma_20 = round(float(close.rolling(20, min_periods=5).mean().iloc[-1]), 2)
        sma_50_val = close.rolling(50, min_periods=25).mean().iloc[-1]
        sma_50 = round(float(sma_50_val), 2) if not pd.isna(sma_50_val) else 0.0

        # ── Trend ──────────────────────────────────────────────
        if sma_50 > 0:
            if current_price > sma_20 > sma_50:
                trend = "Uptrend"
            elif current_price < sma_20 < sma_50:
                trend = "Downtrend"
            else:
                trend = "Sideways"
        else:
            # Use SMA-20 only
            if current_price > sma_20 * 1.01:
                trend = "Uptrend"
            elif current_price < sma_20 * 0.99:
                trend = "Downtrend"
            else:
                trend = "Sideways"

        # ── Bollinger Bands ────────────────────────────────────
        bb_lower, bb_upper, bb_pct = _bollinger(close)
        bb_squeeze = (bb_upper - bb_lower) / current_price < 0.02 if current_price > 0 else False

        # ── Support / Resistance ───────────────────────────────
        support, resistance = _find_support_resistance(low, high, current_price)

        # ── Near support / resistance (within 2%) ─────────────
        near_support    = (current_price - support)    / current_price < 0.02 if current_price > 0 else False
        near_resistance = (resistance - current_price) / current_price < 0.02 if current_price > 0 else False

        return TechnicalData(
            rsi_14=rsi,
            sma_20=sma_20,
            sma_50=sma_50,
            trend=trend,
            support=support,
            resistance=resistance,
            near_support=near_support,
            near_resistance=near_resistance,
            bb_pct=bb_pct,
            bb_squeeze=bb_squeeze,
        )

    except Exception:
        return None
