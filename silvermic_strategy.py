# ─────────────────────────────────────────────────────────────
#  silvermic_strategy.py  –  SILVERMIC VWAP + EMA9/21 + SuperTrend MTF
#
#  Mirrors the TradingView Pine Script strategy (Long Only):
#    - 1H trend filter:  SuperTrend(3,10) + EMA9/21 + RSI > 50
#    - 15m entry:        Above VWAP + EMA9>21 + RSI>52 + bull candle
#                        + pullback to EMA zone + EMA spread %
#    - Exit ladder:      ATR-based trailing stop with 3 profit locks
#    - EOD square-off:   23:25 IST bar open if profit >= ₹10,000 (bigLockProfit)
#
#  Data source: Fyers API history (INR/kg). You must provide get_history().
# ─────────────────────────────────────────────────────────────

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import logging

import numpy as np
import pandas as pd

from fyers_fetcher import get_history  # must return OHLCV with UTC DatetimeIndex

logger = logging.getLogger(__name__)

LOT_SIZE   = 1                      # 1 kg per SILVERMIC lot
IST_OFFSET = timedelta(hours=5, minutes=30)

# Default parameters (match your Pine inputs)
ST_ATR_LEN      = 10
ST_FACTOR       = 3.0
EMA_FAST_LEN    = 9
EMA_SLOW_LEN    = 21
RSI_LEN         = 14
RSI_BULL_LEVEL  = 50.0
ATR_LEN         = 14
ATR_SL_MULT     = 1.5

EMA_SPREAD_MIN  = 0.09              # emaSpreadMinPct
RSI_ENTRY_MIN   = 52.0

CUSHION_TRIGGER = 1500.0
CUSHION_PROFIT  = 1000.0
MID_TRIGGER     = 4000.0
MID_PROFIT      = 2500.0
BIG_TRIGGER     = 11000.0
BIG_PROFIT      = 10000.0

FLAT_HOUR       = 23
FLAT_MINUTE     = 25                # MCX normal session closes 23:30 IST; bar opens 23:15 closes 23:30


# ─────────────────────────────────────────────────────────────
#  Indicator helpers (Series-based)
# ─────────────────────────────────────────────────────────────

def _s_ema(close: pd.Series, span: int) -> pd.Series:
    """EMA series."""
    return close.ewm(span=span, adjust=False).mean()


def _s_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI series (classic Wilder-style using EMA smoothing)."""
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _s_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR series."""
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _s_supertrend(
    df: pd.DataFrame, period: int = 10, factor: float = 3.0
) -> tuple[pd.Series, pd.Series]:
    """
    SuperTrend. Returns (line_series, direction_series).

    direction < 0  →  bullish  (mirrors Pine's ta.supertrend dir = -1 for bull)
    direction > 0  →  bearish
    """
    atr = _s_atr(df, period)
    hl2 = (df["High"] + df["Low"]) / 2
    basic_upper = hl2 + factor * atr
    basic_lower = hl2 - factor * atr

    close_arr = df["Close"].values
    n = len(df)

    final_upper = np.zeros(n)
    final_lower = np.zeros(n)
    direction   = np.ones(n)       # +1 = bearish start
    st_line     = np.zeros(n)

    for i in range(n):
        if i == 0:
            final_upper[i] = float(basic_upper.iloc[i])
            final_lower[i] = float(basic_lower.iloc[i])
            direction[i]   = 1
        else:
            bu = float(basic_upper.iloc[i])
            bl = float(basic_lower.iloc[i])

            # Rolling upper / lower bands
            final_upper[i] = (
                bu
                if (bu < final_upper[i - 1] or close_arr[i - 1] > final_upper[i - 1])
                else final_upper[i - 1]
            )
            final_lower[i] = (
                bl
                if (bl > final_lower[i - 1] or close_arr[i - 1] < final_lower[i - 1])
                else final_lower[i - 1]
            )

            # Direction switch
            if direction[i - 1] == 1:  # was bearish
                direction[i] = -1 if close_arr[i] > final_upper[i] else 1
            else:                      # was bullish (-1)
                direction[i] = 1 if close_arr[i] < final_lower[i] else -1

        st_line[i] = final_lower[i] if direction[i] == -1 else final_upper[i]

    idx = df.index
    return pd.Series(st_line, index=idx), pd.Series(direction, index=idx)


# ─────────────────────────────────────────────────────────────
#  Session VWAP — resets each IST calendar day (≈ ta.vwap)
# ─────────────────────────────────────────────────────────────

def _session_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Daily session VWAP (reset at IST midnight), approximating Pine's ta.vwap
    on intraday charts.[web:284]
    """
    ist_idx = df.index + IST_OFFSET
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    tp_vol = tp * df["Volume"]

    date_grp = [d.date() for d in ist_idx]
    cum_tpv = tp_vol.groupby(date_grp).cumsum()
    cum_vol = df["Volume"].groupby(date_grp).cumsum()
    return cum_tpv / cum_vol.replace(0, np.nan)


# ─────────────────────────────────────────────────────────────
#  1H trend filter (HTF)
# ─────────────────────────────────────────────────────────────

def _htf_filter(
    df_1h: pd.DataFrame,
    st_factor: float = ST_FACTOR,
    st_atr_len: int = ST_ATR_LEN,
    ema_fast: int = EMA_FAST_LEN,
    ema_slow: int = EMA_SLOW_LEN,
    rsi_len: int = RSI_LEN,
    rsi_bull_min: float = RSI_BULL_LEVEL,
    current_price: float | None = None,
) -> dict:
    """
    Evaluate the 1H trend filter using the last completed 1H bar.

    current_price: the current 15m bar's close. Pine's htfBull checks
    'close > stLineHTF' where close is the 15m close, not the 1H close.
    Pass the live 15m close so the comparison matches Pine exactly.
    Falls back to the 1H close when not provided (e.g. live signal calls).
    """
    close = df_1h["Close"]
    st_line, st_dir = _s_supertrend(df_1h, period=st_atr_len, factor=st_factor)
    ema9   = _s_ema(close, ema_fast)
    ema21  = _s_ema(close, ema_slow)
    rsi    = _s_rsi(close, rsi_len)

    htf_close_v = float(close.iloc[-1])       # last completed 1H close
    st_v    = float(st_line.iloc[-1])
    dir_v   = float(st_dir.iloc[-1])
    ema9_v  = float(ema9.iloc[-1])
    ema21_v = float(ema21.iloc[-1])
    rsi_v   = float(rsi.iloc[-1])

    # Pine: htfBull = close > stLineHTF  →  'close' is the 15m bar's close,
    # NOT the 1H bar's close.  Use current_price when available.
    price_ref      = current_price if current_price is not None else htf_close_v
    price_above_st = price_ref > st_v
    st_bullish     = dir_v < 0         # -1 = bull
    ema_bull       = ema9_v > ema21_v
    rsi_bull       = rsi_v > rsi_bull_min
    htf_bull       = price_above_st and st_bullish and ema_bull and rsi_bull

    return dict(
        htf_bull=htf_bull,
        price_above_st=price_above_st,
        st_bullish=st_bullish,
        ema_bull=ema_bull,
        rsi_bull=rsi_bull,
        st_line=round(st_v, 2),
        ema9=round(ema9_v, 2),
        ema21=round(ema21_v, 2),
        rsi=round(rsi_v, 2),
        close=round(htf_close_v, 2),
    )


# ─────────────────────────────────────────────────────────────
#  15m entry conditions
# ─────────────────────────────────────────────────────────────

def _entry_conditions(
    df_15m: pd.DataFrame,
    htf_bull: bool,
    ema_fast: int = EMA_FAST_LEN,
    ema_slow: int = EMA_SLOW_LEN,
    rsi_len: int = RSI_LEN,
    ema_spread_min: float = EMA_SPREAD_MIN,
    rsi_entry_min: float = RSI_ENTRY_MIN,
) -> dict:
    """Evaluate 15m entry conditions using the last completed 15m bar."""
    c     = df_15m["Close"]
    o     = df_15m["Open"]
    lows  = df_15m["Low"]
    vwap  = _session_vwap(df_15m)
    ema9  = _s_ema(c, ema_fast)
    ema21 = _s_ema(c, ema_slow)
    rsi15 = _s_rsi(c, rsi_len)
    atr15 = _s_atr(df_15m, ATR_LEN)

    cv     = float(c.iloc[-1])
    ov     = float(o.iloc[-1])
    lv     = float(lows.iloc[-1])
    ema9_v = float(ema9.iloc[-1])
    ema21_v = float(ema21.iloc[-1])
    vwap_v = float(vwap.iloc[-1]) if not pd.isna(vwap.iloc[-1]) else cv
    rsi_v  = float(rsi15.iloc[-1]) if not pd.isna(rsi15.iloc[-1]) else 50.0
    atr_v  = float(atr15.iloc[-1]) if not pd.isna(atr15.iloc[-1]) else cv * 0.005

    bull_candle = cv > ov
    above_vwap  = cv > vwap_v
    ema_above   = ema9_v > ema21_v
    rsi_ok      = rsi_v > rsi_entry_min
    pullback    = (cv >= ema9_v) and (lv <= ema21_v)
    spread_pct  = abs(ema9_v - ema21_v) / cv * 100 if cv > 0 else 0.0
    strong_trend = spread_pct >= ema_spread_min

    signal_long = (
        htf_bull
        and above_vwap
        and ema_above
        and rsi_ok
        and bull_candle
        and pullback
        and strong_trend
    )

    return dict(
        signal="LONG" if signal_long else "WAIT",
        bull_candle=bull_candle,
        above_vwap=above_vwap,
        ema_above=ema_above,
        rsi_ok=rsi_ok,
        pullback=pullback,
        strong_trend=strong_trend,
        close=round(cv, 2),
        vwap=round(vwap_v, 2),
        ema9=round(ema9_v, 2),
        ema21=round(ema21_v, 2),
        rsi=round(rsi_v, 2),
        spread_pct=round(spread_pct, 3),
        atr=round(atr_v, 2),
        entry_price=round(cv, 2),
        stop_loss=round(cv - atr_v * ATR_SL_MULT, 2),  # Pine: entryPrice - atr15 * atrSLmult
    )


# ─────────────────────────────────────────────────────────────
#  Exit ladder (matches Pine logic)
# ─────────────────────────────────────────────────────────────

def _exit_ladder(
    entry_price: float,
    current_price: float,
    atr: float,
    atr_mult: float = ATR_SL_MULT,
    cushion_trigger: float = CUSHION_TRIGGER,
    cushion_profit: float = CUSHION_PROFIT,
    mid_trigger: float = MID_TRIGGER,
    mid_profit: float = MID_PROFIT,
    big_trigger: float = BIG_TRIGGER,
    big_profit: float = BIG_PROFIT,
) -> dict:
    """
    Calculate trailing stop and profit lock based on current P&L.

    Mirrors Pine:
      baseStop = entryPrice - atr15 * atrSLmult
      profitRs = (close - entryPrice) * pointvalue
      then apply cushion / mid / big locks.
    """
    profit_rs = (current_price - entry_price) * LOT_SIZE
    base_stop = entry_price - atr * atr_mult
    final_stop = base_stop
    level = "Base ATR Stop"

    if profit_rs >= big_trigger:
        lock_stop = entry_price + big_profit / LOT_SIZE
        final_stop = max(final_stop, lock_stop)
        level = f"Big Lock (₹{big_profit:,.0f} secured)"
    elif profit_rs >= mid_trigger:
        lock_stop = entry_price + mid_profit / LOT_SIZE
        final_stop = max(final_stop, lock_stop)
        level = f"Mid Lock (₹{mid_profit:,.0f} secured)"
    elif profit_rs >= cushion_trigger:
        lock_stop = entry_price + cushion_profit / LOT_SIZE
        final_stop = max(final_stop, lock_stop)
        level = f"Cushion Lock (₹{cushion_profit:,.0f} secured)"

    return dict(
        profit_rs=round(profit_rs, 2),
        final_stop=round(final_stop, 2),
        base_stop=round(base_stop, 2),
        level=level,
    )


# ─────────────────────────────────────────────────────────────
#  Backtester – bar-by-bar, no look-ahead
# ─────────────────────────────────────────────────────────────

@dataclass
class Trade:
    entry_time: datetime
    entry_price: float
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    pnl_rs: float = 0.0


def run_backtest(
    df_15m: pd.DataFrame,
    df_1h: pd.DataFrame,
) -> tuple[list[Trade], dict]:
    """
    Bar-by-bar backtest on 15m bars with 1H trend filter.

    - Uses last completed 1H bar as HTF filter (no look-ahead).
    - Stop fires on bar CLOSE (process_orders_on_close=true).
    - EOD: close at bar open >= 23:25 IST only if profit >= BIG_PROFIT (₹10,000).
    """
    trades: list[Trade] = []
    position: Trade | None = None

    # Warm-up for indicators
    for i in range(60, len(df_15m)):
        bar    = df_15m.iloc[: i + 1]
        bar_ts = df_15m.index[i]

        # Only use CLOSED 1H bars (Pine: barmerge.lookahead_off).
        # A 1H bar opening at T closes at T+1h; include it only when T+1h <= bar_ts.
        htf_bars = df_1h[df_1h.index + pd.Timedelta(hours=1) <= bar_ts]
        if len(htf_bars) < 15:
            continue

        c   = float(bar["Close"].iloc[-1])
        # Pass current 15m close so _htf_filter mirrors Pine's
        # 'htfBull = close > stLineHTF' (where close = 15m close, not 1H close).
        htf   = _htf_filter(htf_bars, current_price=c)
        entry = _entry_conditions(bar, htf["htf_bull"])
        atr = entry["atr"]

        # EOD check mirrors Pine's: curH = hour(time), curM = minute(time)
        # Pine uses bar OPEN time for the window check — NOT bar close time.
        # DST bars (23:45 IST open) still fire correctly: 45 >= 25 → True.
        ist = bar_ts + IST_OFFSET
        eod = (ist.hour > FLAT_HOUR) or (
            ist.hour == FLAT_HOUR and ist.minute >= FLAT_MINUTE
        )

        if position is not None:
            ladder = _exit_ladder(position.entry_price, c, atr)
            # Pine uses process_orders_on_close=true: stop fires on CLOSE, not LOW
            hit_stop = c <= ladder["final_stop"]

            if hit_stop:
                position.exit_time = bar_ts
                # process_orders_on_close=true: fill at bar close (min of close and stop)
                position.exit_price = min(c, ladder["final_stop"])
                position.exit_reason = "Stop: " + ladder["level"]
                position.pnl_rs = (position.exit_price - position.entry_price) * LOT_SIZE
                trades.append(position)
                position = None
                # Pine re-entry: after stop-out, if conditions still met on same bar close,
                # a new entry fires immediately (process_orders_on_close behaviour).
                if entry["signal"] == "LONG" and not eod:
                    position = Trade(entry_time=bar_ts, entry_price=c)
            elif eod and ladder["profit_rs"] >= BIG_PROFIT:
                # EOD square-off only if unrealised ≥ bigLockProfit (₹10,000)
                position.exit_time = bar_ts
                position.exit_price = c
                position.exit_reason = "EOD square-off"
                position.pnl_rs = (c - position.entry_price) * LOT_SIZE
                trades.append(position)
                position = None
        else:
            if entry["signal"] == "LONG" and not eod:
                position = Trade(entry_time=bar_ts, entry_price=c)

    # Close any still-open position at end of data
    if position is not None:
        c_last = float(df_15m["Close"].iloc[-1])
        position.exit_time = df_15m.index[-1]
        position.exit_price = c_last
        position.exit_reason = "Backtest end"
        position.pnl_rs = (c_last - position.entry_price) * LOT_SIZE
        trades.append(position)

    # Summary stats
    wins   = [t for t in trades if t.pnl_rs > 0]
    losses = [t for t in trades if t.pnl_rs <= 0]
    total_pnl = sum(t.pnl_rs for t in trades)
    win_rate  = round(len(wins) / len(trades) * 100, 1) if trades else 0.0
    avg_win   = round(sum(t.pnl_rs for t in wins)   / len(wins),   2) if wins   else 0.0
    avg_loss  = round(sum(t.pnl_rs for t in losses) / len(losses), 2) if losses else 0.0

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

    live_price = float(df_15m["Close"].iloc[-1])
    htf = _htf_filter(df_1h, current_price=live_price)
    ent = _entry_conditions(df_15m, htf["htf_bull"])
    return SilverMicResult(
        signal     = ent["signal"],
        htf        = htf,
        entry      = ent,
        fetched_at = datetime.now(timezone.utc),
    )


def backtest(access_token: str, days: int = 140) -> tuple[list[Trade], dict]:
    """Fetch history (up to 140 days) and run a bar-by-bar backtest."""
    today  = (datetime.now(timezone.utc) + IST_OFFSET).strftime("%Y-%m-%d")
    from_d = (datetime.now(timezone.utc) + IST_OFFSET - timedelta(days=days)).strftime("%Y-%m-%d")

    df_1h  = get_history("SILVERMIC", access_token, "60", from_d, today)
    df_15m = get_history("SILVERMIC", access_token, "15", from_d, today)

    if df_1h.empty or df_15m.empty:
        raise RuntimeError("No backtest data — check Fyers token")

    return run_backtest(df_15m, df_1h)