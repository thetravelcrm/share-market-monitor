# ─────────────────────────────────────────────────────────────
#  fyers_fetcher.py  –  Fyers API live price/volume (FREE)
#
#  Auth options:
#    A) Manual OAuth (default):
#       Click "Manual Connect" → Fyers login page → redirects back with token
#
#    B) Auto-Connect via TOTP (zero manual steps):
#       Add to Streamlit Cloud → Settings → Secrets:
#         FYERS_CLIENT_ID   = "<your-client-id>"
#         FYERS_SECRET_KEY  = "<your-secret-key>"
#         FYERS_TOTP_SECRET = "<16-char-secret-from-fyers-totp-setup>"
#         FYERS_PIN         = "<your-4-digit-pin>"
#       Enable TOTP: Fyers Web → My Account → Profile → Others → External 2FA TOTP
#
#    NEVER put real credentials in this file — use Streamlit Cloud Secrets only.
#    Token lasts until midnight IST; one click (or auto) reconnects next morning.
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


def is_auto_login_configured() -> bool:
    """True if TOTP secret + PIN are present in Streamlit secrets."""
    try:
        import streamlit as st
        return bool(
            st.secrets.get("FYERS_TOTP_SECRET") and
            st.secrets.get("FYERS_PIN") and
            is_configured()
        )
    except Exception:
        return False


def auto_login() -> Optional[str]:
    """
    Fully automated Fyers login via TOTP + PIN (Fyers vagator HTTP API).
    No browser or Selenium needed. Returns access_token or None on failure.

    Flow:
      1. POST /send_login_otp  → request_key
      2. POST /verify_otp      → pyotp TOTP code → updated request_key
      3. POST /verify_pin      → SHA-256 hashed PIN → vagator access token
      4. SessionModel.set_token(vagator_token).generate_authcode() → redirect URL
      5. Parse auth_code from redirect URL → exchange_auth_code() → final token
    """
    import requests, pyotp, hashlib, urllib.parse

    cid, sk = _secrets()
    try:
        import streamlit as st
        totp_secret = st.secrets.get("FYERS_TOTP_SECRET", "")
        pin         = st.secrets.get("FYERS_PIN", "")
    except Exception:
        return None

    if not (cid and sk and totp_secret and pin):
        return None

    BASE = "https://api-t2.fyers.in/vagator/v2"
    sess = requests.Session()

    # Step 1 — initiate login
    r1 = sess.post(f"{BASE}/send_login_otp", json={"fy_id": cid, "app_id": "2"})
    if r1.status_code != 200 or r1.json().get("code") != 200:
        return None
    request_key = r1.json()["request_key"]

    # Step 2 — verify TOTP (auto-generated, valid for 30 s window)
    totp_code = pyotp.TOTP(totp_secret).now()
    r2 = sess.post(f"{BASE}/verify_otp",
                   json={"request_key": request_key, "otp": totp_code})
    if r2.status_code != 200 or r2.json().get("code") != 200:
        return None
    request_key = r2.json()["request_key"]

    # Step 3 — verify PIN (SHA-256 hashed)
    pin_hash = hashlib.sha256(pin.encode()).hexdigest()
    r3 = sess.post(f"{BASE}/verify_pin",
                   json={"request_key": request_key, "identity_type": "pin",
                         "identifier": pin_hash})
    if r3.status_code != 200 or r3.json().get("code") != 200:
        return None
    vagator_token = r3.json().get("data", {}).get("access_token", "")
    if not vagator_token:
        return None

    # Step 4 — get auth_code redirect URL via SessionModel
    from fyers_apiv3 import fyersModel
    session = fyersModel.SessionModel(
        client_id=cid, secret_key=sk,
        redirect_uri=REDIRECT_URI,
        response_type="code", grant_type="authorization_code",
    )
    session.set_token(vagator_token)
    redirect_url = session.generate_authcode()

    # Parse auth_code from redirect URL query string
    parsed    = urllib.parse.urlparse(redirect_url)
    auth_code = urllib.parse.parse_qs(parsed.query).get("auth_code", [None])[0]
    if not auth_code:
        return None

    # Step 5 — exchange for final access token
    return exchange_auth_code(auth_code)


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
