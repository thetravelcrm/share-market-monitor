# ─────────────────────────────────────────────────────────────
#  fyers_fetcher.py  –  Fyers API live price/volume (FREE)
#
#  Auto-refreshes the access token daily using TOTP + PIN.
#  No manual steps needed once secrets are configured.
#
#  Add to Streamlit Cloud → Settings → Secrets:
#    FYERS_CLIENT_ID  = "IFT522ZFF6-100"
#    FYERS_SECRET_KEY = "UZDMXT07DG"
#    FYERS_USER_ID    = "XY1234"
#    FYERS_PIN        = "1234"
#    FYERS_TOTP_KEY   = "JBSWY3DPEHPK3PXP"
# ─────────────────────────────────────────────────────────────
from __future__ import annotations
from typing import Optional
import time

_fyers       = None
_token_ts    = 0.0          # epoch when token was last fetched
_TOKEN_TTL   = 23 * 3600    # refresh every 23 hours (tokens expire at midnight)


def _secrets() -> dict:
    try:
        import streamlit as st
        return {
            "client_id":  st.secrets.get("FYERS_CLIENT_ID", ""),
            "secret_key": st.secrets.get("FYERS_SECRET_KEY", ""),
            "user_id":    st.secrets.get("FYERS_USER_ID", ""),
            "pin":        st.secrets.get("FYERS_PIN", ""),
            "totp_key":   st.secrets.get("FYERS_TOTP_KEY", ""),
        }
    except Exception:
        return {}


def _is_configured(s: dict) -> bool:
    return all(s.get(k) for k in ("client_id", "secret_key", "user_id", "pin", "totp_key"))


def _init_fyers(force: bool = False):
    """Return a live FyersModel, refreshing the token when needed."""
    global _fyers, _token_ts
    s = _secrets()
    if not _is_configured(s):
        return None

    age = time.time() - _token_ts
    if _fyers is not None and not force and age < _TOKEN_TTL:
        return _fyers

    try:
        from fyers_auth import get_access_token
        from fyers_apiv3 import fyersModel
        token = get_access_token(
            client_id  = s["client_id"],
            secret_key = s["secret_key"],
            user_id    = s["user_id"],
            pin        = s["pin"],
            totp_key   = s["totp_key"],
        )
        _fyers    = fyersModel.FyersModel(
            client_id=s["client_id"],
            is_async=False,
            token=token,
            log_path="",
        )
        _token_ts = time.time()
        return _fyers
    except Exception as e:
        print(f"[Fyers] token refresh failed: {e}")
        return None


def is_available() -> bool:
    return _is_configured(_secrets())


def get_quote(symbol: str) -> Optional[dict]:
    """
    Fetch live NSE quote via Fyers API.
    Returns dict with: last_price, volume, change_pct, prev_close, high, low, open
    Returns None if Fyers not configured or symbol not found.
    """
    fyers = _init_fyers()
    if fyers is None:
        return None
    try:
        resp = fyers.quotes({"symbols": f"NSE:{symbol}-EQ"})
        if resp.get("code") != 200:
            return None
        d = resp.get("d", [{}])[0].get("v", {})
        if not d:
            return None
        prev_close = d.get("prev_close_price", d.get("lp", 0))
        last_price = d.get("lp", 0)
        change_pct = round((last_price - prev_close) / prev_close * 100, 2) if prev_close else 0.0
        return {
            "last_price": last_price,
            "volume":     int(d.get("volume", 0)),
            "change_pct": change_pct,
            "prev_close": prev_close,
            "high":       d.get("high_price", last_price),
            "low":        d.get("low_price", last_price),
            "open":       d.get("open_price", last_price),
        }
    except Exception:
        return None
