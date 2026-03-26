# ─────────────────────────────────────────────────────────────
#  fyers_fetcher.py  –  Fyers API live price/volume (FREE)
#
#  One-time setup:
#    1. Go to https://myapi.fyers.in/dashboard → create an app
#       Set redirect URI to: https://arshadshare.streamlit.app
#    2. Run `python fyers_auth.py` locally to get your access token
#    3. In Streamlit Cloud → Settings → Secrets, add:
#         FYERS_CLIENT_ID   = "XXXXXXXX-100"   # your app's client ID
#         FYERS_ACCESS_TOKEN = "eyJ..."         # token from fyers_auth.py
#    4. Access token expires daily — re-run fyers_auth.py each morning
#       OR use fyers_auth.py's auto-refresh if you store refresh_token too
# ─────────────────────────────────────────────────────────────
from __future__ import annotations
from typing import Optional

_fyers = None


def _init_fyers():
    """Initialize FyersModel from Streamlit secrets. Returns None if not configured."""
    global _fyers
    if _fyers is not None:
        return _fyers
    try:
        import streamlit as st
        client_id    = st.secrets.get("FYERS_CLIENT_ID", "")
        access_token = st.secrets.get("FYERS_ACCESS_TOKEN", "")
        if not client_id or not access_token:
            return None
        from fyers_apiv3 import fyersModel
        _fyers = fyersModel.FyersModel(
            client_id=client_id,
            is_async=False,
            token=access_token,
            log_path="",
        )
        return _fyers
    except Exception:
        return None


def is_available() -> bool:
    return _init_fyers() is not None


def get_quote(symbol: str) -> Optional[dict]:
    """
    Fetch live NSE quote via Fyers API.
    symbol: NSE symbol e.g. "RELIANCE", "HDFCBANK"
    Returns dict with: last_price, volume, change_pct, prev_close, high, low, open
    Returns None if Fyers not configured or symbol not found.
    """
    fyers = _init_fyers()
    if fyers is None:
        return None
    try:
        # Fyers symbol format: NSE:SYMBOL-EQ
        fyers_sym = f"NSE:{symbol}-EQ"
        resp = fyers.quotes({"symbols": fyers_sym})
        if resp.get("code") != 200:
            return None
        d = resp.get("d", [{}])[0].get("v", {})
        if not d:
            return None
        prev_close = d.get("prev_close_price", d.get("lp", 0))
        last_price = d.get("lp", 0)
        change_pct = round((last_price - prev_close) / prev_close * 100, 2) if prev_close else 0.0
        return {
            "last_price":  last_price,
            "volume":      int(d.get("volume", 0)),
            "change_pct":  change_pct,
            "prev_close":  prev_close,
            "high":        d.get("high_price", last_price),
            "low":         d.get("low_price", last_price),
            "open":        d.get("open_price", last_price),
            "bid":         d.get("bid", 0),
            "ask":         d.get("ask", 0),
        }
    except Exception:
        return None
