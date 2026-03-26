# ─────────────────────────────────────────────────────────────
#  fyers_fetcher.py  –  Fyers API live price/volume (FREE)
#
#  OAuth flow — no TOTP needed:
#    1. Add to Streamlit Cloud → Settings → Secrets:
#         FYERS_CLIENT_ID  = "IFT522ZFF6-100"
#         FYERS_SECRET_KEY = "UZDMXT07DG"
#    2. In your Fyers API dashboard, set Redirect URI to:
#         https://arshadshare.streamlit.app
#    3. In the app sidebar, click "Connect Fyers" → log in normally
#       The app auto-captures the auth code from the redirect URL.
#    Token lasts until midnight; reconnect next morning with one click.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations
from typing import Optional

REDIRECT_URI = "https://arshadshare.streamlit.app"


def _secrets() -> tuple[str, str]:
    """Return (client_id, secret_key) from Streamlit secrets."""
    try:
        import streamlit as st
        return (
            st.secrets.get("FYERS_CLIENT_ID", ""),
            st.secrets.get("FYERS_SECRET_KEY", ""),
        )
    except Exception:
        return "", ""


def is_configured() -> bool:
    cid, sk = _secrets()
    return bool(cid and sk)


def get_auth_url() -> str:
    """Generate the Fyers login URL to send the user to."""
    from fyers_apiv3 import fyersModel
    cid, sk = _secrets()
    session = fyersModel.SessionModel(
        client_id=cid,
        secret_key=sk,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        grant_type="authorization_code",
    )
    return session.generate_authcode()


def exchange_auth_code(auth_code: str) -> Optional[str]:
    """Exchange an auth code (from redirect URL) for an access token."""
    try:
        from fyers_apiv3 import fyersModel
        cid, sk = _secrets()
        session = fyersModel.SessionModel(
            client_id=cid,
            secret_key=sk,
            redirect_uri=REDIRECT_URI,
            response_type="code",
            grant_type="authorization_code",
        )
        session.set_token(auth_code)
        resp = session.generate_token()
        if resp.get("code") == 200:
            return resp["access_token"]
        return None
    except Exception:
        return None


def get_fyers_model(access_token: str):
    """Return a FyersModel ready for API calls."""
    from fyers_apiv3 import fyersModel
    cid, _ = _secrets()
    return fyersModel.FyersModel(
        client_id=cid,
        is_async=False,
        token=access_token,
        log_path="",
    )


def get_quote(symbol: str, access_token: str) -> Optional[dict]:
    """
    Fetch live NSE quote via Fyers API.
    Returns dict with: last_price, volume, change_pct, prev_close, high, low, open
    """
    try:
        fyers = get_fyers_model(access_token)
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
