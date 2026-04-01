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
    """True if FYERS_ID, TOTP secret + PIN are present in Streamlit secrets."""
    try:
        import streamlit as st
        return bool(
            st.secrets.get("FYERS_ID") and
            st.secrets.get("FYERS_TOTP_SECRET") and
            st.secrets.get("FYERS_PIN") and
            is_configured()
        )
    except Exception:
        return False


def auto_login() -> tuple[Optional[str], str]:
    """
    Fully automated Fyers login via TOTP + PIN (Fyers vagator HTTP API).
    Returns (access_token, "") on success, (None, error_message) on failure.

    Flow:
      1. POST /send_login_otp  → request_key
      2. POST /verify_otp      → pyotp TOTP code → updated request_key
      3. POST /verify_pin      → SHA-256 hashed PIN → vagator access token
      4. POST api/v3/token     → auth_code
      5. exchange_auth_code()  → final access_token
    """
    import requests, pyotp, hashlib, urllib.parse

    cid, sk = _secrets()
    try:
        import streamlit as st
        totp_secret = st.secrets.get("FYERS_TOTP_SECRET", "")
        pin         = st.secrets.get("FYERS_PIN", "")
    except Exception:
        return None, "Could not read Streamlit secrets"

    try:
        fyers_id = st.secrets.get("FYERS_ID", "")   # user's Fyers login ID (e.g. XY12345)
    except Exception:
        fyers_id = ""

    if not cid or not sk:
        return None, "FYERS_CLIENT_ID or FYERS_SECRET_KEY missing in secrets"
    if not fyers_id:
        return None, "FYERS_ID missing in secrets (your Fyers login ID, e.g. XY12345)"
    if not totp_secret:
        return None, "FYERS_TOTP_SECRET missing in secrets"
    if not pin:
        return None, "FYERS_PIN missing in secrets"

    BASE = "https://api-t2.fyers.in/vagator/v2"
    sess = requests.Session()

    # Step 1 — initiate login (fy_id = user's Fyers login ID, not API client_id)
    try:
        r1 = sess.post(f"{BASE}/send_login_otp", json={"fy_id": fyers_id, "app_id": "2"}, timeout=10)
        d1 = r1.json()
        if d1.get("s") != "ok":
            return None, f"Step1 send_login_otp failed: {d1}"
        request_key = d1["request_key"]
    except Exception as e:
        return None, f"Step1 network error: {e}"

    # Step 2 — verify TOTP
    try:
        totp_code = pyotp.TOTP(totp_secret).now()
        r2 = sess.post(f"{BASE}/verify_otp",
                       json={"request_key": request_key, "otp": totp_code}, timeout=10)
        d2 = r2.json()
        if d2.get("s") != "ok":
            return None, f"Step2 verify_otp failed: {d2}"
        request_key = d2["request_key"]
    except Exception as e:
        return None, f"Step2 TOTP error: {e}"

    # Step 3 — verify PIN
    # Fyers vagator v2 expects plain PIN string (not hashed)
    try:
        r3 = sess.post(f"{BASE}/verify_pin",
                       json={"request_key": request_key, "identity_type": "pin",
                             "identifier": pin}, timeout=10)
        d3 = r3.json()
        if d3.get("s") != "ok":
            # Fallback: try SHA-256 hashed
            pin_hash = hashlib.sha256(pin.encode()).hexdigest()
            r3b = sess.post(f"{BASE}/verify_pin",
                            json={"request_key": request_key, "identity_type": "pin",
                                  "identifier": pin_hash}, timeout=10)
            d3 = r3b.json()
            if d3.get("s") != "ok":
                return None, f"Step3 verify_pin failed (plain+hashed both tried): {d3}"
        vagator_token = d3.get("data", {}).get("access_token", "")
        if not vagator_token:
            return None, f"Step3 no access_token in response: {d3}"
    except Exception as e:
        return None, f"Step3 PIN error: {e}"

    # Step 4 — get auth_code via Fyers token API
    # Try three Authorization header variants that different Fyers SDK versions expect
    try:
        app_id_short = cid.split("-")[0]   # "IFT522ZFF6" from "IFT522ZFF6-100"
        payload4 = {
            "fyers_id":       fyers_id,
            "app_id":         app_id_short,
            "redirect_uri":   REDIRECT_URI,
            "appType":        "100",
            "code_challenge": "",
            "state":          "None",
            "nonce":          "",
            "response_type":  "code",
            "create_cookie":  True,
        }
        _auth_code = None
        _last_d4   = {}
        for _auth_header in [
            f"{cid}:{vagator_token}",          # variant A: full client_id:token
            f"{app_id_short}:{vagator_token}", # variant B: short app_id:token
            vagator_token,                     # variant C: bare token
        ]:
            r4 = sess.post(
                "https://api-t1.fyers.in/api/v3/token",
                headers={"Authorization": _auth_header,
                         "Content-Type": "application/json"},
                json=payload4,
                timeout=10,
            )
            _last_d4 = r4.json()
            _redirect_url = _last_d4.get("Url", "")
            if _redirect_url:
                _parsed   = urllib.parse.urlparse(_redirect_url)
                _auth_code = urllib.parse.parse_qs(_parsed.query).get("auth_code", [None])[0]
                if _auth_code:
                    break
        if not _auth_code:
            return None, f"Step4 token API failed (all variants tried): {_last_d4}"
        auth_code = _auth_code
    except Exception as e:
        return None, f"Step4 token API error: {e}"

    # Step 5 — exchange auth_code for final access token
    try:
        token = exchange_auth_code(auth_code)
        if not token:
            return None, "Step5 exchange_auth_code returned None"
        return token, ""
    except Exception as e:
        return None, f"Step5 exchange error: {e}"


# MCX commodity symbols that should use MCX exchange prefix in Fyers
_MCX_SYMBOLS = {"SILVERMIC", "GOLDM", "CRUDEOIL", "NATURALGAS",
                "COPPER", "ZINC", "ALUMINIUM", "NICKEL", "LEAD"}


def _mcx_fyers_symbol(symbol: str) -> str:
    """
    Build the active near-month Fyers MCX symbol.
    Fyers format: MCX:SILVERMIC26APR  (symbol + 2-digit-year + 3-letter-month)
    Uses the current month; if today is past the 25th, rolls to next month
    (MCX contracts typically expire on the last day of the month).
    """
    from datetime import datetime, timezone, timedelta
    ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    # Roll to next month if within last 5 days of month (contract near expiry)
    if ist.day >= 26:
        if ist.month == 12:
            exp = ist.replace(year=ist.year + 1, month=1, day=1)
        else:
            exp = ist.replace(month=ist.month + 1, day=1)
    else:
        exp = ist
    yy  = exp.strftime("%y")       # "26"
    mmm = exp.strftime("%b").upper()  # "APR"
    return f"MCX:{symbol}{yy}{mmm}"


def get_quote(symbol: str, access_token: str) -> Optional[dict]:
    """
    Fetch live quote via Fyers API — NSE equities or MCX futures.
    Returns dict with: last_price, volume, change_pct, prev_close, high, low, open
    """
    try:
        fyers = get_fyers_model(access_token)
        if symbol in _MCX_SYMBOLS:
            fyers_sym = _mcx_fyers_symbol(symbol)
        else:
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
