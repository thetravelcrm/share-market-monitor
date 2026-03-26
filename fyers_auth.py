# ─────────────────────────────────────────────────────────────
#  fyers_auth.py  –  Fully automated Fyers token generator
#
#  Uses TOTP + PIN so NO manual browser steps are needed.
#  Called automatically by fyers_fetcher.py when the token expires.
#
#  Required Streamlit secrets (Settings → Secrets in Streamlit Cloud):
#    FYERS_CLIENT_ID  = "IFT522ZFF6-100"
#    FYERS_SECRET_KEY = "UZDMXT07DG"
#    FYERS_USER_ID    = "XY1234"        ← your Fyers login ID
#    FYERS_PIN        = "1234"          ← your Fyers 4-digit PIN
#    FYERS_TOTP_KEY   = "JBSWY3DPEHPK3PXP"  ← TOTP secret (see below)
#
#  How to get your TOTP secret key:
#    1. Log into Fyers → My Account → Security Settings
#    2. Disable existing TOTP, then re-enable it
#    3. When the QR code appears, also click "Can't scan? View key"
#    4. Copy that base32 text — that is your FYERS_TOTP_KEY
# ─────────────────────────────────────────────────────────────
from __future__ import annotations
import requests
import pyotp
from urllib.parse import urlparse, parse_qs

REDIRECT_URI = "https://arshadshare.streamlit.app"
_LOGIN_OTP_URL  = "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
_VERIFY_OTP_URL = "https://api-t2.fyers.in/vagator/v2/verify_otp"
_VERIFY_PIN_URL = "https://api-t2.fyers.in/vagator/v2/verify_pin_v2"
_TOKEN_URL      = "https://api-t1.fyers.in/api/v3/token"


def get_access_token(
    client_id: str,
    secret_key: str,
    user_id: str,
    pin: str,
    totp_key: str,
) -> str:
    """
    Fully automated Fyers login using TOTP + PIN.
    Returns a fresh access token. Raises on any failure.
    """
    from fyers_apiv3 import fyersModel

    # Step 1 — build auth URL (we need app_id from it)
    session = fyersModel.SessionModel(
        client_id=client_id,
        secret_key=secret_key,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        grant_type="authorization_code",
    )
    session.generate_authcode()   # populates session internals

    # Step 2 — send OTP to registered mobile
    r = requests.post(_LOGIN_OTP_URL, json={"fy_id": user_id, "app_id": "2"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("s") != "ok":
        raise RuntimeError(f"send_login_otp failed: {data}")
    request_key = data["request_key"]

    # Step 3 — verify TOTP
    totp_code = pyotp.TOTP(totp_key).now()
    r = requests.post(_VERIFY_OTP_URL, json={"request_key": request_key, "otp": totp_code}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("s") != "ok":
        raise RuntimeError(f"verify_otp failed: {data}")
    request_key = data["request_key"]

    # Step 4 — verify PIN
    r = requests.post(
        _VERIFY_PIN_URL,
        json={"request_key": request_key, "identity_type": "pin", "identifier": pin},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("s") != "ok":
        raise RuntimeError(f"verify_pin failed: {data}")
    login_token = data["data"]["access_token"]

    # Step 5 — exchange login token for API auth code
    app_id = client_id.split("-")[0]   # "IFT522ZFF6" from "IFT522ZFF6-100"
    headers = {"Authorization": f"Bearer {login_token}"}
    payload = {
        "fyers_id":      user_id,
        "app_id":        app_id,
        "redirect_uri":  REDIRECT_URI,
        "appType":       "100",
        "code_challenge": "",
        "state":         "None",
        "nonce":         "",
        "response_type": "code",
        "create_cookie": True,
    }
    r = requests.post(_TOKEN_URL, json=payload, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("s") != "ok":
        raise RuntimeError(f"token endpoint failed: {data}")
    auth_code = data["Url"].split("auth_code=")[1].split("&")[0]

    # Step 6 — exchange auth code for access token
    session.set_token(auth_code)
    resp = session.generate_token()
    if resp.get("code") != 200:
        raise RuntimeError(f"generate_token failed: {resp}")
    return resp["access_token"]


if __name__ == "__main__":
    # Run locally to test: python fyers_auth.py
    client_id  = input("FYERS_CLIENT_ID  : ").strip()
    secret_key = input("FYERS_SECRET_KEY : ").strip()
    user_id    = input("FYERS_USER_ID    : ").strip()
    pin        = input("FYERS_PIN        : ").strip()
    totp_key   = input("FYERS_TOTP_KEY   : ").strip()
    try:
        token = get_access_token(client_id, secret_key, user_id, pin, totp_key)
        print(f"\n✅ Access Token:\n{token}\n")
        print("Add to Streamlit Secrets as FYERS_ACCESS_TOKEN")
    except Exception as e:
        print(f"\n❌ Error: {e}")
