# ─────────────────────────────────────────────────────────────
#  silvermic_strategy.py  –  SILVERMIC VWAP + EMA9/21 + SuperTrend MTF
#
#  Mirrors the TradingView Pine Script strategy (Long Only):
#    - 1H trend filter:  SuperTrend + EMA9/21 + RSI > 50
#    - 15m entry:        Above VWAP + EMA9>21 + RSI>52 + bull candle
#                        + pullback to EMA zone + EMA spread
#    - Exit ladder:      ATR-based trailing stop with 3 profit locks
#    - EOD square-off:   23:35 IST if profit >= ₹2500
#
#  Data source: Fyers API (returns MCX data already in INR/kg)
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

from fyers_fetcher import get_history

logger = logging.getLogger(__name__)

LOT_SIZE   = 1          # 1 kg per MCX SILVERMIC lot
IST_OFFSET = timedelta(hours=5, minutes=30)


# ─────────────────────────────────────────────────────────────
#  Local Series-returning indicator helpers
#  (technical_analyzer.py helpers return scalars — we need
#  full Series here for bar-by-bar slicing in the backtest)
# ─────────────────────────────────────────────────────────────

def _s_ema(close: pd.Series, span: int) -> pd.Series:
    """EMA Series."""
    return close.ewm(span=span, adjust=False).mean()


def _s_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI Series."""
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _s_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR Series."""
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _s_supertrend(df: pd.DataFrame, period: int = 10,
                  factor: float = 3.0) -> tuple[pd.Series, pd.Series]:
    """
    SuperTrend.  Returns (line_series, direction_series).
    direction < 0  →  bullish  (mirrors Pine's direction = -1 when bull)
    direction > 0  →  bearish
    """
    atr          = _s_atr(df, period)
    hl2          = (df["High"] + df["Low"]) / 2
    basic_upper  = hl2 + factor * atr
    basic_lower  = hl2 - factor * atr
    close_arr    = df["Close"].values
    n            = len(df)

    final_upper = np.zeros(n)
    final_lower = np.zeros(n)
    direction   = np.ones(n)      # +1 = bearish start
    st_line     = np.zeros(n)

    for i in range(n):
        if i == 0:
            final_upper[i] = float(basic_upper.iloc[i])
            final_lower[i] = float(basic_lower.iloc[i])
            direction[i]   = 1
        else:
            bu = float(basic_upper.iloc[i])
            bl = float(basic_lower.iloc[i])
            final_upper[i] = bu if (bu < final_upper[i - 1] or close_arr[i - 1] > final_upper[i - 1]) else final_upper[i - 1]
            final_lower[i] = bl if (bl > final_lower[i - 1] or close_arr[i - 1] < final_lower[i - 1]) else final_lower[i - 1]
            if direction[i - 1] == 1:     # was bearish
                direction[i] = -1 if close_arr[i] > final_upper[i] else 1
            else:                          # was bullish (-1)
                direction[i] = 1 if close_arr[i] < final_lower[i] else -1
        st_line[i] = final_lower[i] if direction[i] == -1 else final_upper[i]

    idx = df.index
    return pd.Series(st_line, index=idx), pd.Series(direction, index=idx)


# ─────────────────────────────────────────────────────────────
#  Session VWAP — resets each IST calendar day
# ─────────────────────────────────────────────────────────────

def _session_vwap(df: pd.DataFrame) -> pd.Series:
    """Daily session VWAP (reset at IST midnight), mirroring ta.vwap in Pine."""
    ist_idx  = df.index + IST_OFFSET
    tp       = (df["High"] + df["Low"] + df["Close"]) / 3
    tp_vol   = tp * df["Volume"]
    # Group by IST date for cumulative sum reset
    date_grp = [d.date() for d in ist_idx]
    cum_tpv  = tp_vol.groupby(date_grp).cumsum()
    cum_vol  = df["Volume"].groupby(date_grp).cumsum()
    return cum_tpv / cum_vol.replace(0, np.nan)


# ─────────────────────────────────────────────────────────────
#  1H trend filter
# ─────────────────────────────────────────────────────────────

def _htf_filter(df_1h: pd.DataFrame,
                st_factor: float = 3.0, st_atr_len: int = 10,
                ema_fast: int = 9, ema_slow: int = 21,
                rsi_len: int = 14, rsi_bull_min: float = 50.0) -> dict:
    """Evaluate the 1H trend filter. Uses last completed bar (.iloc[-1])."""
    c         = df_1h["Close"]
    st_line, st_dir = _s_supertrend(df_1h, period=st_atr_len, factor=st_factor)
    ema9      = _s_ema(c, ema_fast)
    ema21     = _s_ema(c, ema_slow)
    rsi       = _s_rsi(c, rsi_len)

    close_v         = float(c.iloc[-1])
    st_line_v       = float(st_line.iloc[-1])
    st_dir_v        = float(st_dir.iloc[-1])
    ema9_v          = float(ema9.iloc[-1])
    ema21_v         = float(ema21.iloc[-1])
    rsi_v           = float(rsi.iloc[-1])

    price_above_st  = close_v > st_line_v
    st_bullish      = st_dir_v < 0          # -1 = bull in our convention
    ema_bull        = ema9_v > ema21_v
    rsi_bull        = rsi_v > rsi_bull_min
    htf_bull        = price_above_st and st_bullish and ema_bull and rsi_bull

    return dict(
        htf_bull       = htf_bull,
        price_above_st = price_above_st,
        st_bullish     = st_bullish,
        ema_bull       = ema_bull,
        rsi_bull       = rsi_bull,
        st_line        = round(st_line_v, 2),
        ema9           = round(ema9_v, 2),
        ema21          = round(ema21_v, 2),
        rsi            = round(rsi_v, 2),
        close          = round(close_v, 2),
    )


# ─────────────────────────────────────────────────────────────
#  15m entry conditions
# ─────────────────────────────────────────────────────────────

def _entry_conditions(df_15m: pd.DataFrame, htf_bull: bool,
                      ema_fast: int = 9, ema_slow: int = 21,
                      rsi_len: int = 14,
                      ema_spread_min: float = 0.09,
                      rsi_entry_min: float = 52.0) -> dict:
    """Evaluate 15m entry conditions. Uses last completed bar (.iloc[-1])."""
    c     = df_15m["Close"]
    o     = df_15m["Open"]
    lows  = df_15m["Low"]
    vwap  = _session_vwap(df_15m)
    ema9  = _s_ema(c, ema_fast)
    ema21 = _s_ema(c, ema_slow)
    rsi15 = _s_rsi(c, rsi_len)
    atr15 = _s_atr(df_15m, 14)

    cv    = float(c.iloc[-1])
    ov    = float(o.iloc[-1])
    lv    = float(lows.iloc[-1])
    ema9v = float(ema9.iloc[-1])
    ema21v= float(ema21.iloc[-1])
    vwapv = float(vwap.iloc[-1]) if not pd.isna(vwap.iloc[-1]) else cv
    rsi15v= float(rsi15.iloc[-1]) if not pd.isna(rsi15.iloc[-1]) else 50.0
    atr15v= float(atr15.iloc[-1]) if not pd.isna(atr15.iloc[-1]) else cv * 0.005

    bull_candle  = cv > ov
    above_vwap   = cv > vwapv
    ema_above    = ema9v > ema21v
    rsi_ok       = rsi15v > rsi_entry_min
    pullback     = (cv >= ema9v) and (lv <= ema21v)
    spread_pct   = abs(ema9v - ema21v) / cv * 100 if cv > 0 else 0.0
    strong_trend = spread_pct >= ema_spread_min
    signal_long  = (htf_bull and above_vwap and ema_above and rsi_ok
                    and bull_candle and pullback and strong_trend)

    return dict(
        signal       = "LONG" if signal_long else "WAIT",
        bull_candle  = bull_candle,
        above_vwap   = above_vwap,
        ema_above    = ema_above,
        rsi_ok       = rsi_ok,
        pullback     = pullback,
        strong_trend = strong_trend,
        close        = round(cv, 2),
        vwap         = round(vwapv, 2),
        ema9         = round(ema9v, 2),
        ema21        = round(ema21v, 2),
        rsi          = round(rsi15v, 2),
        spread_pct   = round(spread_pct, 3),
        entry_price  = round(cv, 2),
        stop_loss    = round(cv - atr15v * 1.5, 2),
        atr          = round(atr15v, 2),
    )


# ─────────────────────────────────────────────────────────────
#  Exit ladder (3-tier profit lock)
# ─────────────────────────────────────────────────────────────

def _exit_ladder(entry: float, current: float, atr: float,
                 cushion_trigger: float = 1500, cushion_profit: float = 1000,
                 mid_trigger: float = 4000,    mid_profit: float = 2500,
                 big_trigger: float = 11000,   big_profit: float = 10000,
                 atr_mult: float = 1.5) -> dict:
    """Calculate trailing stop and profit lock based on current P&L."""
    profit_rs  = (current - entry) * LOT_SIZE
    base_stop  = entry - atr * atr_mult
    final_stop = base_stop
    level      = "Base ATR Stop"

    if profit_rs >= big_trigger:
        final_stop = max(final_stop, entry + big_profit / LOT_SIZE)
        level      = f"Big Lock (₹{big_profit:,.0f} secured)"
    elif profit_rs >= mid_trigger:
        final_stop = max(final_stop, entry + mid_profit / LOT_SIZE)
        level      = f"Mid Lock (₹{mid_profit:,.0f} secured)"
    elif profit_rs >= cushion_trigger:
        final_stop = max(final_stop, entry + cushion_profit / LOT_SIZE)
        level      = f"Cushion Lock (₹{cushion_profit:,.0f} secured)"

    return dict(
        profit_rs  = round(profit_rs, 2),
        final_stop = round(final_stop, 2),
        base_stop  = round(base_stop, 2),
        level      = level,
    )


# ─────────────────────────────────────────────────────────────
#  Backtester — bar-by-bar, no look-ahead
# ─────────────────────────────────────────────────────────────

@dataclass
class Trade:
    entry_time:  datetime
    entry_price: float
    entry_atr:   float           = 0.0    # frozen at entry for consistent stop
    exit_time:   datetime | None = None
    exit_price:  float | None    = None
    exit_reason: str             = ""
    pnl_rs:      float           = 0.0    # ₹ P&L per lot


def run_backtest(df_15m: pd.DataFrame, df_1h: pd.DataFrame,
                 params: dict | None = None) -> tuple[list[Trade], dict]:
    """
    Bar-by-bar backtest on 15m bars with 1H trend filter.
    Warm-up: first 60 bars skipped to allow indicators to stabilise.
    Returns (trades, summary_dict).
    """
    p = params or {}
    st_factor      = p.get("st_factor",      3.0)
    st_atr_len     = p.get("st_atr_len",     10)
    ema_fast       = p.get("ema_fast",        9)
    ema_slow       = p.get("ema_slow",        21)
    rsi_len        = p.get("rsi_len",         14)
    rsi_bull_min   = p.get("rsi_bull_min",    50.0)
    ema_spread_min = p.get("ema_spread_min",  0.09)
    rsi_entry_min  = p.get("rsi_entry_min",   52.0)
    atr_sl_mult    = p.get("atr_sl_mult",     1.5)
    flat_hour      = p.get("flat_hour",       23)
    flat_min       = p.get("flat_min",        15)   # MCX closes 23:30 IST; last 15m bar starts 23:15
    eod_min_profit = p.get("eod_min_profit",  2500)

    trades:   list[Trade] = []
    position: Trade | None = None

    for i in range(60, len(df_15m)):
        bar    = df_15m.iloc[: i + 1]
        bar_ts = df_15m.index[i]

        # Last 1H bars up to this 15m timestamp
        htf_bars = df_1h[df_1h.index <= bar_ts]
        if len(htf_bars) < 15:
            continue

        htf   = _htf_filter(htf_bars, st_factor, st_atr_len,
                             ema_fast, ema_slow, rsi_len, rsi_bull_min)
        entry = _entry_conditions(bar, htf["htf_bull"], ema_fast, ema_slow,
                                  rsi_len, ema_spread_min, rsi_entry_min)

        c   = float(bar["Close"].iloc[-1])
        low = float(bar["Low"].iloc[-1])
        atr = entry["atr"]
        ist = bar_ts + IST_OFFSET
        eod = ist.hour > flat_hour or (ist.hour == flat_hour and ist.minute >= flat_min)

        if position is not None:
            # Use ATR frozen at entry so stop level doesn't drift between bars
            ladder   = _exit_ladder(position.entry_price, c, position.entry_atr)
            # Use bar Low for stop check (mirrors TradingView bar-by-bar fill)
            hit_stop = low <= ladder["final_stop"]
            if hit_stop:
                position.exit_time   = bar_ts
                position.exit_price  = ladder["final_stop"]
                position.exit_reason = "Stop: " + ladder["level"]
                position.pnl_rs      = (position.exit_price - position.entry_price) * LOT_SIZE
                trades.append(position)
                position = None
            elif eod:
                # Close ALL positions at EOD (mirrors TradingView strategy.close_all)
                position.exit_time   = bar_ts
                position.exit_price  = c
                position.exit_reason = "EOD square-off"
                position.pnl_rs      = (c - position.entry_price) * LOT_SIZE
                trades.append(position)
                position = None
        else:
            if entry["signal"] == "LONG" and not eod:
                position = Trade(entry_time=bar_ts, entry_price=c, entry_atr=atr)

    # Close any still-open position at end of data
    if position is not None:
        c_last = float(df_15m["Close"].iloc[-1])
        position.exit_time   = df_15m.index[-1]
        position.exit_price  = c_last
        position.exit_reason = "Backtest end"
        position.pnl_rs      = (c_last - position.entry_price) * LOT_SIZE
        trades.append(position)

    # Summary statistics
    wins      = [t for t in trades if t.pnl_rs > 0]
    losses    = [t for t in trades if t.pnl_rs <= 0]
    total_pnl = sum(t.pnl_rs for t in trades)
    win_rate  = round(len(wins) / len(trades) * 100, 1) if trades else 0.0
    avg_win   = round(sum(t.pnl_rs for t in wins)   / len(wins),   2) if wins   else 0.0
    avg_loss  = round(sum(t.pnl_rs for t in losses) / len(losses), 2) if losses else 0.0

    # Max drawdown on equity curve
    equity = [0.0]
    for t in trades:
        equity.append(equity[-1] + t.pnl_rs)
    peak   = 0.0
    max_dd = 0.0
    for e in equity:
        peak   = max(peak, e)
        max_dd = min(max_dd, e - peak)

    summary = dict(
        total        = len(trades),
        wins         = len(wins),
        losses       = len(losses),
        win_rate     = win_rate,
        total_pnl    = round(total_pnl, 2),
        avg_win      = avg_win,
        avg_loss     = avg_loss,
        max_drawdown = round(max_dd, 2),
        equity       = equity,
    )
    return trades, summary


# ─────────────────────────────────────────────────────────────
#  Public entry points
# ─────────────────────────────────────────────────────────────

@dataclass
class SilverMicResult:
    signal:     str
    htf:        dict
    entry:      dict
    fetched_at: datetime


def analyze(access_token: str) -> SilverMicResult:
    """Fetch live bars and return current signal state."""
    today    = (datetime.now(timezone.utc) + IST_OFFSET).strftime("%Y-%m-%d")
    from_1h  = (datetime.now(timezone.utc) + IST_OFFSET - timedelta(days=30)).strftime("%Y-%m-%d")
    from_15m = (datetime.now(timezone.utc) + IST_OFFSET - timedelta(days=5)).strftime("%Y-%m-%d")

    df_1h  = get_history("SILVERMIC", access_token, "60", from_1h,  today)
    df_15m = get_history("SILVERMIC", access_token, "15", from_15m, today)

    if df_1h.empty or df_15m.empty or len(df_15m) < 30:
        raise RuntimeError("Insufficient data — check Fyers token")

    htf = _htf_filter(df_1h)
    ent = _entry_conditions(df_15m, htf["htf_bull"])
    return SilverMicResult(
        signal     = ent["signal"],
        htf        = htf,
        entry      = ent,
        fetched_at = datetime.now(timezone.utc),
    )


def backtest(access_token: str, days: int = 90) -> tuple[list[Trade], dict]:
    """Fetch history (up to 90 days) and run a bar-by-bar backtest."""
    today  = (datetime.now(timezone.utc) + IST_OFFSET).strftime("%Y-%m-%d")
    from_d = (datetime.now(timezone.utc) + IST_OFFSET - timedelta(days=days)).strftime("%Y-%m-%d")

    df_1h  = get_history("SILVERMIC", access_token, "60", from_d, today)
    df_15m = get_history("SILVERMIC", access_token, "15", from_d, today)

    if df_1h.empty or df_15m.empty:
        raise RuntimeError("No backtest data — check Fyers token")

    return run_backtest(df_15m, df_1h)
