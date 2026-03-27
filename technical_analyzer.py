# ─────────────────────────────────────────────────────────────
#  technical_analyzer.py  –  RSI, SMA, MACD, Stochastic, ATR,
#  EMA, OBV, Bollinger, Support/Resistance
#  All calculations use only pandas/numpy — no extra packages.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import numpy as np


@dataclass
class TechnicalData:
    # ── Existing indicators ────────────────────────────────────
    rsi_14: float          # 0–100  (< 35 oversold, > 65 overbought)
    sma_20: float          # 20-day simple moving average
    sma_50: float          # 50-day SMA (0.0 if not enough data)
    trend: str             # "Uptrend" | "Downtrend" | "Sideways"
    support: float         # strongest recent support level
    resistance: float      # strongest recent resistance level
    near_support: bool     # price within 2% above support
    near_resistance: bool  # price within 2% below resistance
    bb_pct: float          # Bollinger %B  (0=lower band, 1=upper band)
    bb_squeeze: bool       # bands tight (< 2% of price)

    # ── MACD (12, 26, 9) — needs 35+ bars ─────────────────────
    macd_line: float       = 0.0
    macd_signal: float     = 0.0
    macd_histogram: float  = 0.0
    macd_bullish: bool     = False   # True when macd_line > macd_signal

    # ── Stochastic (14, 3) — needs 14+ bars ───────────────────
    stoch_k: float         = 0.0
    stoch_d: float         = 0.0
    stoch_oversold: bool   = False   # stoch_k < 20
    stoch_overbought: bool = False   # stoch_k > 80

    # ── EMA(9) — needs 9+ bars ─────────────────────────────────
    ema_9: float           = 0.0
    price_above_ema9: bool = False

    # ── ATR(14) — needs 15+ bars ──────────────────────────────
    atr_14: float          = 0.0
    atr_pct: float         = 0.0    # ATR / price * 100 (normalised vol %)

    # ── OBV Trend — needs 5+ bars ─────────────────────────────
    obv_trend: str         = "Neutral"  # "Rising" | "Falling" | "Neutral"


# ─────────────────────────────────────────────────────────────
#  Private helpers — existing
# ─────────────────────────────────────────────────────────────

def _rsi(close: pd.Series, period: int = 14) -> float:
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.rolling(period, min_periods=period).mean().iloc[-1]
    avg_loss = loss.rolling(period, min_periods=period).mean().iloc[-1]
    if pd.isna(avg_gain) or pd.isna(avg_loss):
        return 50.0
    if avg_loss == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_gain / avg_loss), 2)


def _bollinger(close: pd.Series, period: int = 20) -> tuple[float, float, float]:
    """Return (lower_band, upper_band, %B)."""
    if len(close) < period:
        c = float(close.iloc[-1])
        return c, c, 0.5
    sma   = close.rolling(period).mean().iloc[-1]
    std   = close.rolling(period).std().iloc[-1]
    upper = sma + 2 * std
    lower = sma - 2 * std
    cur   = float(close.iloc[-1])
    bb_pct = (cur - lower) / (upper - lower) if (upper - lower) > 0 else 0.5
    return round(lower, 2), round(upper, 2), round(bb_pct, 3)


def _find_support_resistance(
    lows: pd.Series, highs: pd.Series, current_price: float, lookback: int = 20
) -> tuple[float, float]:
    recent_lows  = lows.iloc[-lookback:]
    recent_highs = highs.iloc[-lookback:]
    pivot_lows   = [recent_lows.iloc[i]  for i in range(1, len(recent_lows)  - 1)
                    if recent_lows.iloc[i]  <= recent_lows.iloc[i-1]  and recent_lows.iloc[i]  <= recent_lows.iloc[i+1]]
    pivot_highs  = [recent_highs.iloc[i] for i in range(1, len(recent_highs) - 1)
                    if recent_highs.iloc[i] >= recent_highs.iloc[i-1] and recent_highs.iloc[i] >= recent_highs.iloc[i+1]]
    support    = min(pivot_lows)  if pivot_lows  else float(recent_lows.min())
    resistance = max(pivot_highs) if pivot_highs else float(recent_highs.max())
    if support    >= current_price: support    = float(recent_lows.min())
    if resistance <= current_price: resistance = float(recent_highs.max())
    return round(support, 2), round(resistance, 2)


# ─────────────────────────────────────────────────────────────
#  Private helpers — new indicators
# ─────────────────────────────────────────────────────────────

def _ema(close: pd.Series, span: int) -> float:
    """Generic EMA. Returns 0.0 if insufficient data."""
    if len(close) < span:
        return 0.0
    return round(float(close.ewm(span=span, adjust=False).mean().iloc[-1]), 2)


def _macd(close: pd.Series) -> tuple[float, float, float, bool]:
    """MACD(12,26,9). Returns (line, signal, histogram, is_bullish). Needs 35+ bars."""
    if len(close) < 35:
        return 0.0, 0.0, 0.0, False
    ema12    = close.ewm(span=12, adjust=False).mean()
    ema26    = close.ewm(span=26, adjust=False).mean()
    macd_ser = ema12 - ema26
    sig_ser  = macd_ser.ewm(span=9, adjust=False).mean()
    m = float(macd_ser.iloc[-1])
    s = float(sig_ser.iloc[-1])
    return round(m, 4), round(s, 4), round(m - s, 4), m > s


def _stochastic(
    close: pd.Series, high: pd.Series, low: pd.Series
) -> tuple[float, float, bool, bool]:
    """Stochastic(14,3). Returns (K, D, oversold, overbought). Needs 14+ bars."""
    if len(close) < 14:
        return 0.0, 0.0, False, False
    lo14  = low.rolling(14).min()
    hi14  = high.rolling(14).max()
    denom = (hi14 - lo14).replace(0, np.nan)
    k_ser = ((close - lo14) / denom * 100).fillna(50.0)
    d_ser = k_ser.rolling(3).mean()
    kv    = round(float(k_ser.iloc[-1]), 2)
    dv    = round(float(d_ser.iloc[-1]) if not pd.isna(d_ser.iloc[-1]) else kv, 2)
    return kv, dv, kv < 20, kv > 80


def _atr(
    high: pd.Series, low: pd.Series, close: pd.Series, current_price: float
) -> tuple[float, float]:
    """ATR(14). Returns (atr_value, atr_pct). Needs 15+ bars."""
    if len(close) < 15:
        return 0.0, 0.0
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr_val = round(float(tr.rolling(14).mean().iloc[-1]), 4)
    atr_pct = round(atr_val / current_price * 100, 2) if current_price > 0 else 0.0
    return atr_val, atr_pct


def _obv_trend(close: pd.Series, volume: pd.Series) -> str:
    """OBV slope over last 5 bars. Returns 'Rising'|'Falling'|'Neutral'."""
    if len(close) < 5:
        return "Neutral"
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv       = (direction * volume).cumsum()
    slope     = float(obv.iloc[-1]) - float(obv.iloc[-5])
    if slope > 0:
        return "Rising"
    elif slope < 0:
        return "Falling"
    return "Neutral"


# ─────────────────────────────────────────────────────────────
#  Main entry point
# ─────────────────────────────────────────────────────────────

def compute_technicals(hist: pd.DataFrame, current_price: float) -> Optional[TechnicalData]:
    """
    Compute all technical indicators from a yfinance history DataFrame.
    `hist` must have columns: Close, High, Low, Volume with a DatetimeIndex.
    Returns None if there is insufficient data.
    """
    try:
        if hist is None or hist.empty or len(hist) < 15:
            return None

        close  = hist["Close"].dropna()
        high   = hist["High"].dropna()
        low    = hist["Low"].dropna()
        volume = hist["Volume"].dropna()

        if len(close) < 15:
            return None

        # ── RSI ────────────────────────────────────────────────
        rsi = _rsi(close)

        # ── SMA ────────────────────────────────────────────────
        sma_20     = round(float(close.rolling(20, min_periods=5).mean().iloc[-1]), 2)
        sma_50_val = close.rolling(50, min_periods=25).mean().iloc[-1]
        sma_50     = round(float(sma_50_val), 2) if not pd.isna(sma_50_val) else 0.0

        # ── Trend ──────────────────────────────────────────────
        if sma_50 > 0:
            if current_price > sma_20 > sma_50:
                trend = "Uptrend"
            elif current_price < sma_20 < sma_50:
                trend = "Downtrend"
            else:
                trend = "Sideways"
        else:
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

        # ── EMA(9) ─────────────────────────────────────────────
        ema9_val       = _ema(close, 9)
        price_above_e9 = current_price > ema9_val if ema9_val > 0 else False

        # ── MACD(12,26,9) ──────────────────────────────────────
        macd_l, macd_s, macd_h, macd_bull = _macd(close)

        # ── Stochastic(14,3) ───────────────────────────────────
        stoch_k, stoch_d, st_os, st_ob = _stochastic(close, high, low)

        # ── ATR(14) ────────────────────────────────────────────
        atr_val, atr_pct_val = _atr(high, low, close, current_price)

        # ── OBV Trend ──────────────────────────────────────────
        obv_t = _obv_trend(close, volume)

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
            # new indicators
            macd_line=macd_l,
            macd_signal=macd_s,
            macd_histogram=macd_h,
            macd_bullish=macd_bull,
            stoch_k=stoch_k,
            stoch_d=stoch_d,
            stoch_oversold=st_os,
            stoch_overbought=st_ob,
            ema_9=ema9_val,
            price_above_ema9=price_above_e9,
            atr_14=atr_val,
            atr_pct=atr_pct_val,
            obv_trend=obv_t,
        )

    except Exception:
        return None
