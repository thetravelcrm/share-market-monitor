# ─────────────────────────────────────────────────────────────
#  silvermic_continuous.py
#  Backwards-adjusted continuous SILVERMIC series.
#
#  SILVERMIC has bi-monthly expiries:  Apr(J), Jun(M), Aug(Q), Nov(X).
#  At each rollover the new contract trades a few hundred to a few thousand
#  rupees above/below the expiring one (contango / backwardation).  Naive
#  concatenation creates phantom gaps that fake out Supertrend / EMA / ATR.
#
#  This module fetches each contract only for its front-month window,
#  computes the price gap at each rollover, and adds it to all older prices
#  so the series is continuous.  Volume is NOT adjusted.
#
#  Use this for both backtest and live signal generation.  The most-recent
#  segment is unadjusted, so the latest close equals the live front-month
#  contract price — no offset needed for manual order placement.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import logging

import pandas as pd

from fyers_fetcher import get_fyers_model

logger = logging.getLogger(__name__)

IST_OFFSET = timedelta(hours=5, minutes=30)

# SILVERMIC active expiry months → Fyers 3-letter month code
_EXPIRY_MONTHS = {4: "APR", 6: "JUN", 8: "AUG", 11: "NOV"}

# Roll to next contract this many days before expiry (MCX silver dies on liquidity)
ROLLOVER_DAYS_BEFORE_EXPIRY = 3


def _contract_symbol(year: int, month: int) -> str:
    """Fyers MCX history symbol, e.g. 'MCX:SILVERMIC26APRFUT'."""
    return f"MCX:SILVERMIC{year % 100:02d}{_EXPIRY_MONTHS[month]}FUT"


def _approx_expiry(year: int, month: int) -> datetime:
    """MCX silver expires on the last working day of the month; use day 28 (UTC)."""
    return datetime(year, month, 28, tzinfo=timezone.utc)


def _list_contracts(start: datetime, end: datetime) -> list[dict]:
    """All SILVERMIC contracts whose expiry is within our extended range."""
    out = []
    for yr in range(start.year - 1, end.year + 2):
        for mo in sorted(_EXPIRY_MONTHS):
            exp = _approx_expiry(yr, mo)
            out.append({"symbol": _contract_symbol(yr, mo),
                        "expiry": exp, "year": yr, "month": mo})
    out.sort(key=lambda c: c["expiry"])
    return [c for c in out
            if c["expiry"] >= start - timedelta(days=120)
            and c["expiry"] <= end + timedelta(days=30)]


def _fetch_one(symbol: str, token: str, resolution: str,
               d_from: str, d_to: str) -> pd.DataFrame:
    """Fetch OHLCV for one specific contract (cont_flag=0)."""
    try:
        fyers = get_fyers_model(token)
        resp = fyers.history({
            "symbol":      symbol,
            "resolution":  resolution,
            "date_format": "1",
            "range_from":  d_from,
            "range_to":    d_to,
            "cont_flag":   "0",
        })
        if resp.get("s") != "ok":
            return pd.DataFrame()
        candles = resp.get("candles", [])
        if not candles:
            return pd.DataFrame()
        df = pd.DataFrame(candles,
                          columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        return df.set_index("timestamp").sort_index()
    except Exception as e:
        logger.warning("fetch failed for %s: %s", symbol, e)
        return pd.DataFrame()


def get_continuous(token: str, resolution: str, days_back: int = 180) -> pd.DataFrame:
    """
    Backwards-adjusted continuous SILVERMIC series.

    resolution: "15", "60", "D"
    days_back:  how far back from now (IST)

    Returns a DataFrame with UTC DatetimeIndex and columns Open/High/Low/Close/Volume.
    Older segments are price-shifted so rollover gaps disappear.  The newest
    segment is unadjusted, so the last close matches the live front-month quote.
    """
    now_ist = datetime.now(timezone.utc) + IST_OFFSET
    start   = now_ist - timedelta(days=days_back)
    end     = now_ist

    contracts = _list_contracts(start, end)
    if not contracts:
        return pd.DataFrame()

    # Each contract's front-month window = (prev_rollover, own_rollover]
    rollovers = [c["expiry"] - timedelta(days=ROLLOVER_DAYS_BEFORE_EXPIRY)
                 for c in contracts]

    segments: list[dict] = []
    for i, c in enumerate(contracts):
        active_from = rollovers[i - 1] if i > 0 else (rollovers[i] - timedelta(days=90))
        active_to   = rollovers[i]

        # Skip segments entirely outside the user's window
        if active_to < start - timedelta(days=5) or active_from > end:
            continue

        f = max(active_from, start - timedelta(days=5)).strftime("%Y-%m-%d")
        t = min(active_to,   end).strftime("%Y-%m-%d")
        df = _fetch_one(c["symbol"], token, resolution, f, t)
        if df.empty:
            logger.info("no data for %s window %s → %s", c["symbol"], f, t)
            continue
        segments.append({"contract": c, "df": df})

    if not segments:
        return pd.DataFrame()

    # Compute rollover gap for each junction and apply backwards.
    # Walk from newest to oldest; each gap shifts all earlier segments.
    for i in range(len(segments) - 1, 0, -1):
        older = segments[i - 1]
        newer = segments[i]

        older_last_ts    = older["df"].index[-1]
        older_last_close = float(older["df"]["Close"].iloc[-1])

        # Fetch newer contract around the transition (±3 days for weekends/holidays)
        # Use daily resolution: one close per day is enough and is the most
        # reliable for far-month contracts that may not print every 15m bar.
        from_d = (older_last_ts - timedelta(days=3)).strftime("%Y-%m-%d")
        to_d   = (older_last_ts + timedelta(days=3)).strftime("%Y-%m-%d")
        newer_window = _fetch_one(
            newer["contract"]["symbol"], token, "D", from_d, to_d,
        )
        if newer_window.empty:
            logger.warning("cannot compute gap at %s (no newer data); skipping adjust",
                           older_last_ts)
            continue

        newer_price = newer_window["Close"].asof(older_last_ts)
        if pd.isna(newer_price):
            newer_price = float(newer_window["Close"].iloc[0])

        gap = float(newer_price) - older_last_close
        if abs(gap) < 1e-6:
            continue

        # Shift ALL earlier segments (0..i-1) by +gap so their prices align with newer
        for j in range(i):
            for col in ("Open", "High", "Low", "Close"):
                segments[j]["df"][col] = segments[j]["df"][col] + gap

    result = pd.concat([s["df"] for s in segments]).sort_index()
    result = result[~result.index.duplicated(keep="last")]
    return result
