# ─────────────────────────────────────────────────────────────
#  technical_analyzer.py  –  RSI, SMA, MACD, Stochastic, ATR,
#  EMA, OBV, Bollinger, Support/Resistance
#  All calculations use only pandas/numpy — no extra packages.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


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

    # ── ADX(14) — needs 28+ bars ──────────────────────────────
    adx_14: float          = 0.0        # 0–100  (> 25 = strong trend)
    adx_trending: bool     = False      # ADX > 25

    # ── SuperTrend(10, 3) — needs 12+ bars ────────────────────
    supertrend_bullish: Optional[bool] = None  # None = insufficient data

    # ── CCI(20) — needs 20+ bars ──────────────────────────────
    cci_20: float          = 0.0
    cci_oversold: bool     = False      # CCI < −100
    cci_overbought: bool   = False      # CCI > +100

    # ── VWAP(5) — 5-day rolling VWAP ────────────────────────
    vwap_5d: float         = 0.0
    price_above_vwap: bool = False

    # ── Market Regime ────────────────────────────────────────
    market_regime: str     = "Unknown"  # "Trending"|"Sideways"|"HighVol"|"LowLiquidity"

    # ── Smart Money / Volume Analysis ────────────────────────
    volume_spike: bool     = False      # current vol > 2x 20-day avg
    volume_dry: bool       = False      # current vol < 0.5x avg
    pre_breakout: bool     = False      # rising OBV + BB squeeze + low vol


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


def _adx(high: pd.Series, low: pd.Series, close: pd.Series) -> tuple[float, bool]:
    """ADX(14) — trend strength. Returns (adx_value, is_trending). Needs 28+ bars."""
    if len(close) < 28:
        return 0.0, False
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    up_move   = high - prev_high
    down_move = prev_low - low
    plus_dm   = pd.Series(
        np.where((up_move > down_move) & (up_move > 0),   up_move,   0.0),
        index=close.index,
    )
    minus_dm  = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=close.index,
    )
    alpha      = 1 / 14
    tr14       = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di14  = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean()  / tr14.replace(0, np.nan)
    minus_di14 = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / tr14.replace(0, np.nan)
    di_sum     = (plus_di14 + minus_di14).replace(0, np.nan)
    dx         = (100 * (plus_di14 - minus_di14).abs() / di_sum).fillna(0)
    adx_val    = round(float(dx.ewm(alpha=alpha, adjust=False).mean().iloc[-1]), 2)
    return adx_val, adx_val > 25


def _supertrend(
    high: pd.Series, low: pd.Series, close: pd.Series,
    period: int = 10, multiplier: float = 3.0,
) -> Optional[bool]:
    """SuperTrend(10, 3). Returns True=bullish, False=bearish, None=insufficient data."""
    n = len(close)
    if n < period + 2:
        return None
    prev_close  = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr          = tr.ewm(alpha=1 / period, adjust=False).mean()
    hl2          = (high + low) / 2
    basic_upper  = (hl2 + multiplier * atr).values
    basic_lower  = (hl2 - multiplier * atr).values
    close_arr    = close.values
    final_upper  = basic_upper.copy()
    final_lower  = basic_lower.copy()
    trend        = np.ones(n, dtype=int)   # 1=bullish, −1=bearish
    for i in range(1, n):
        final_upper[i] = (
            basic_upper[i]
            if basic_upper[i] < final_upper[i - 1] or close_arr[i - 1] > final_upper[i - 1]
            else final_upper[i - 1]
        )
        final_lower[i] = (
            basic_lower[i]
            if basic_lower[i] > final_lower[i - 1] or close_arr[i - 1] < final_lower[i - 1]
            else final_lower[i - 1]
        )
        if trend[i - 1] == -1:
            trend[i] = 1 if close_arr[i] > final_upper[i] else -1
        else:
            trend[i] = -1 if close_arr[i] < final_lower[i] else 1
    return bool(trend[-1] == 1)


def _cci(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20
) -> tuple[float, bool, bool]:
    """CCI(20). Returns (cci_value, oversold, overbought). Needs 20+ bars."""
    if len(close) < period:
        return 0.0, False, False
    tp       = (high + low + close) / 3
    sma_tp   = tp.rolling(period).mean()
    mean_dev = tp.rolling(period).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True
    )
    denom    = (0.015 * mean_dev).replace(0, np.nan)
    cci_ser  = (tp - sma_tp) / denom
    raw      = cci_ser.iloc[-1]
    cci_val  = round(float(raw) if not pd.isna(raw) else 0.0, 2)
    return cci_val, cci_val < -100, cci_val > 100


def _vwap(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series,
    period: int = 5,
) -> float:
    """Rolling VWAP over `period` daily bars. Returns 0.0 if insufficient data."""
    if len(close) < period or volume.iloc[-period:].sum() == 0:
        return 0.0
    typical = (high + low + close) / 3
    vwap_val = (typical * volume).rolling(period).sum() / volume.rolling(period).sum()
    val = vwap_val.iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else 0.0


def _detect_regime(
    adx_val: float, atr_pct: float, bb_squeeze: bool, vol_ratio: float,
) -> str:
    """Classify market regime from technical inputs."""
    if vol_ratio < 0.5:
        return "LowLiquidity"
    if atr_pct > 4.0:
        return "HighVol"
    if adx_val > 25:
        return "Trending"
    return "Sideways"


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

        # Drop rows where ANY of the required columns is NaN so all series
        # stay perfectly aligned by index (prevents stochastic/OBV mismatches)
        hist_clean = hist[["Close", "High", "Low", "Volume"]].dropna()
        close  = hist_clean["Close"]
        high   = hist_clean["High"]
        low    = hist_clean["Low"]
        volume = hist_clean["Volume"]

        if len(close) < 15:
            return None

        # ── RSI ────────────────────────────────────────────────
        rsi = _rsi(close)

        # ── SMA ────────────────────────────────────────────────
        sma_20     = round(float(close.rolling(20, min_periods=5).mean().iloc[-1]), 2)
        sma_50_val = close.rolling(50, min_periods=25).mean().iloc[-1]
        sma_50     = round(float(sma_50_val), 2) if not pd.isna(sma_50_val) else 0.0

        # ── Trend (SMA50 fallback uses EMA approximation) ─────
        if sma_50 > 0:
            if current_price > sma_20 > sma_50:
                trend = "Uptrend"
            elif current_price < sma_20 < sma_50:
                trend = "Downtrend"
            else:
                trend = "Sideways"
        else:
            ema_50_approx = _ema(close, min(50, len(close)))
            if ema_50_approx > 0 and current_price > sma_20 > ema_50_approx:
                trend = "Uptrend"
            elif ema_50_approx > 0 and current_price < sma_20 < ema_50_approx:
                trend = "Downtrend"
            elif current_price > sma_20 * 1.01:
                trend = "Uptrend"
            elif current_price < sma_20 * 0.99:
                trend = "Downtrend"
            else:
                trend = "Sideways"

        # ── Bollinger Bands ────────────────────────────────────
        bb_lower, bb_upper, bb_pct = _bollinger(close)
        bb_squeeze = (bb_upper - bb_lower) / current_price < 0.02 if current_price > 0 else False

        # ── ATR(14) — compute early for adaptive thresholds ────
        atr_val, atr_pct_val = _atr(high, low, close, current_price)

        # ── Support / Resistance ───────────────────────────────
        support, resistance = _find_support_resistance(low, high, current_price)

        # ── Near support / resistance (ATR-adaptive threshold) ─
        sr_threshold = max(0.02, atr_pct_val / 100 * 1.5) if atr_pct_val > 0 else 0.02
        near_support    = (current_price - support)    / current_price < sr_threshold if current_price > 0 else False
        near_resistance = (resistance - current_price) / current_price < sr_threshold if current_price > 0 else False

        # ── EMA(9) ─────────────────────────────────────────────
        ema9_val       = _ema(close, 9)
        price_above_e9 = current_price > ema9_val if ema9_val > 0 else False

        # ── MACD(12,26,9) ──────────────────────────────────────
        macd_l, macd_s, macd_h, macd_bull = _macd(close)

        # ── Stochastic(14,3) ───────────────────────────────────
        stoch_k, stoch_d, st_os, st_ob = _stochastic(close, high, low)

        # ── OBV Trend ──────────────────────────────────────────
        obv_t = _obv_trend(close, volume)

        # ── ADX(14) ────────────────────────────────────────────
        adx_val, adx_trd = _adx(high, low, close)

        # ── SuperTrend(10, 3) ──────────────────────────────────
        st_bull = _supertrend(high, low, close)

        # ── CCI(20) ────────────────────────────────────────────
        cci_val, cci_os, cci_ob = _cci(high, low, close)

        # ── VWAP(5) ───────────────────────────────────────────
        vwap_val = _vwap(high, low, close, volume)
        above_vwap = current_price > vwap_val if vwap_val > 0 else False

        # ── Volume Analysis (smart money) ─────────────────────
        avg_vol_20 = float(volume.iloc[-20:].mean()) if len(volume) >= 20 else float(volume.mean())
        cur_vol    = float(volume.iloc[-1]) if len(volume) > 0 else 0.0
        vol_ratio_tech = cur_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0
        v_spike    = vol_ratio_tech > 2.0
        v_dry      = vol_ratio_tech < 0.5
        pre_bo     = obv_t == "Rising" and bb_squeeze and vol_ratio_tech < 1.2

        # ── Market Regime ─────────────────────────────────────
        regime = _detect_regime(adx_val, atr_pct_val, bb_squeeze, vol_ratio_tech)

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
            adx_14=adx_val,
            adx_trending=adx_trd,
            supertrend_bullish=st_bull,
            cci_20=cci_val,
            cci_oversold=cci_os,
            cci_overbought=cci_ob,
            vwap_5d=vwap_val,
            price_above_vwap=above_vwap,
            market_regime=regime,
            volume_spike=v_spike,
            volume_dry=v_dry,
            pre_breakout=pre_bo,
        )

    except Exception as exc:
        logger.error("compute_technicals failed: %s", exc)
        return None
