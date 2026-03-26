# ─────────────────────────────────────────────────────────────
#  kite_fetcher.py  –  Zerodha Kite Connect live price/volume
#
#  Setup (one-time):
#    1. Add to .streamlit/secrets.toml:
#         KITE_API_KEY    = "your_api_key"
#         KITE_ACCESS_TOKEN = "your_access_token"   # refresh daily
#    2. pip install kiteconnect
#
#  Falls back to yfinance if credentials not configured.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations
from typing import Optional

_kite = None   # singleton KiteConnect session


def _init_kite():
    """Initialize KiteConnect from Streamlit secrets. Returns None if not configured."""
    global _kite
    if _kite is not None:
        return _kite
    try:
        import streamlit as st
        api_key    = st.secrets.get("KITE_API_KEY", "")
        acc_token  = st.secrets.get("KITE_ACCESS_TOKEN", "")
        if not api_key or not acc_token:
            return None
        from kiteconnect import KiteConnect
        _kite = KiteConnect(api_key=api_key)
        _kite.set_access_token(acc_token)
        return _kite
    except Exception:
        return None


def get_quote(symbol: str) -> Optional[dict]:
    """
    Fetch live NSE quote via Kite Connect.
    Returns dict with keys: last_price, volume, oi, change, change_pct
    Returns None if Kite not configured or symbol not found.
    """
    kite = _init_kite()
    if kite is None:
        return None
    try:
        instrument = f"NSE:{symbol}"
        data = kite.quote([instrument])
        q = data.get(instrument, {})
        if not q:
            return None
        ohlc      = q.get("ohlc", {})
        prev_close = ohlc.get("close", q.get("last_price", 0))
        last_price = q.get("last_price", 0)
        change_pct = round((last_price - prev_close) / prev_close * 100, 2) if prev_close else 0.0
        return {
            "last_price":  last_price,
            "volume":      q.get("volume", 0),
            "buy_qty":     q.get("buy_quantity", 0),
            "sell_qty":    q.get("sell_quantity", 0),
            "oi":          q.get("oi", 0),            # open interest (F&O)
            "prev_close":  prev_close,
            "change_pct":  change_pct,
            "high":        ohlc.get("high", 0),
            "low":         ohlc.get("low", 0),
            "open":        ohlc.get("open", 0),
        }
    except Exception:
        return None


def is_available() -> bool:
    """Returns True if Kite credentials are configured."""
    return _init_kite() is not None
