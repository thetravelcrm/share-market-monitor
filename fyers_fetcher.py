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


def _sec(name: str, default: str = "") -> str:
    """
    Read a secret from Streamlit secrets first, then environment variables.
    The env fallback lets the headless cron runner (GitHub Actions) use the same
    auth code as the Streamlit app, where there is no st.secrets file.
    """
    try:
        import streamlit as st
        v = st.secrets.get(name, "")
        if v:
            return str(v)
    except Exception:
        pass
    import os
    return os.environ.get(name, default)


def _secrets() -> tuple[str, str]:
    """Return (client_id, secret_key) from Streamlit secrets or environment."""
    return _sec("FYERS_CLIENT_ID"), _sec("FYERS_SECRET_KEY")


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


def get_positions(access_token: str) -> Optional[dict]:
    """
    Live open positions from Fyers (read-only). Returns
        {"positions": [{symbol, side, net_qty, avg, ltp, pl, product}, …],
         "total_pl": float}
    or None on any error (callers degrade gracefully).
    """
    try:
        fyers = get_fyers_model(access_token)
        resp = fyers.positions()
        if resp.get("s") != "ok" and resp.get("code") != 200:
            return None
        out = []
        for p in resp.get("netPositions", []) or []:
            try:
                qty = int(p.get("netQty", 0) or 0)
            except Exception:
                qty = 0
            out.append({
                "symbol":  p.get("symbol", ""),
                "side":    "LONG" if qty > 0 else ("SHORT" if qty < 0 else "FLAT"),
                "net_qty": qty,
                "avg":     float(p.get("netAvg", 0) or 0),
                "ltp":     float(p.get("ltp", 0) or 0),
                "pl":      float(p.get("pl", 0) or 0),
                "product": p.get("productType", ""),
            })
        total = (resp.get("overall") or {}).get("pl_total")
        if total is None:
            total = sum(x["pl"] for x in out)
        return {"positions": out, "total_pl": float(total)}
    except Exception:
        return None


def get_depth(symbols: list[str], access_token: str) -> dict:
    """
    Full market depth (5 levels) for MCX/NSE symbols — the ladder, not just the touch,
    so order size can be priced honestly.
    Returns {symbol: {"bids": [{price, volume}…], "asks": [{price, volume}…]}}.
    Missing/failed symbols are simply absent.
    """
    out: dict = {}
    if not symbols:
        return out
    try:
        fyers = get_fyers_model(access_token)
        for i in range(0, len(symbols), 10):          # chunk: depth is heavier than quotes
            chunk = symbols[i:i + 10]
            try:
                resp = fyers.depth({"symbol": ",".join(chunk), "ohlcv_flag": "1"})
            except Exception:
                continue
            if resp.get("s") != "ok" and resp.get("code") != 200:
                continue
            for sym, d in (resp.get("d") or {}).items():
                # Fyers names the ask side "ask" (some versions "asks").
                asks = d.get("ask") or d.get("asks") or []
                bids = d.get("bids") or d.get("bid") or []
                def _lvls(raw):
                    out_l = []
                    for lv in raw or []:
                        try:
                            px, vol = float(lv.get("price", 0)), int(lv.get("volume", 0))
                        except Exception:
                            continue
                        if px > 0 and vol > 0:
                            out_l.append({"price": px, "volume": vol})
                    return out_l
                b, a = _lvls(bids), _lvls(asks)
                if b and a:
                    b.sort(key=lambda x: -x["price"])   # best bid first
                    a.sort(key=lambda x: x["price"])    # best ask first
                    out[sym] = {"bids": b, "asks": a}
    except Exception:
        pass
    return out


def is_auto_login_configured() -> bool:
    """True if FYERS_ID, TOTP secret + PIN are present (Streamlit secrets or env)."""
    return bool(
        _sec("FYERS_ID") and
        _sec("FYERS_TOTP_SECRET") and
        _sec("FYERS_PIN") and
        is_configured()
    )


def _verify_totp_step(sess, base: str, request_key: str, totp_secret: str):
    """
    Step 2 of auto-login: verify the TOTP. Hardened against the common failure modes:
      - normalises the secret (strips spaces, upper-cases) and validates it is base32;
      - never generates a code in the last 3s of a 30s window (it would roll mid-request);
      - retries ONCE on a fresh window if Fyers returns -1063 'invalid totp' (a benign
        boundary/skew miss), but no more — to avoid burning attempts / blocking the account;
      - on final failure, returns the code it generated + IST time so the user can compare
        with their authenticator app (mismatch == wrong secret; match == clock skew).
    Returns (new_request_key, "") on success, (None, error_message) on failure.
    """
    import pyotp
    import time as _t
    from datetime import datetime, timezone, timedelta

    secret = (totp_secret or "").strip().replace(" ", "").upper()
    try:
        totp = pyotp.TOTP(secret)
        totp.now()                      # forces a base32 decode — fails fast if malformed
    except Exception as e:
        return None, ("FYERS_TOTP_SECRET is not a valid TOTP key (base32 decode failed: "
                      f"{e}). Re-copy it from Fyers → My Account → Profile → Others → "
                      "External 2FA TOTP.")

    last: dict = {}
    for attempt in range(2):
        pos = _t.time() % 30
        if pos > 27:                    # too close to the boundary — wait for the next window
            _t.sleep(30 - pos + 0.5)
        code = totp.now()
        try:
            last = sess.post(f"{base}/verify_otp",
                             json={"request_key": request_key, "otp": code}, timeout=10).json()
        except Exception as e:
            return None, f"network error: {e}"
        if last.get("s") == "ok":
            return last["request_key"], ""
        # Only retry the benign 'invalid totp' (-1063), and only once on a fresh window.
        if last.get("code") != -1063 or attempt == 1:
            break
        _t.sleep(30 - (_t.time() % 30) + 0.5)

    gen = totp.now()
    ist = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%H:%M:%S")
    return None, (f"verify_otp failed: {last}. The app's secret generated code {gen} at "
                  f"{ist} IST — open your Fyers authenticator: if that 6-digit code differs, "
                  "FYERS_TOTP_SECRET is wrong (re-copy from Fyers → Profile → External 2FA "
                  "TOTP). If it matches, the server clock is skewed.")


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
    totp_secret = _sec("FYERS_TOTP_SECRET")
    pin         = _sec("FYERS_PIN")
    fyers_id    = _sec("FYERS_ID")   # user's Fyers login ID (e.g. XY12345)

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

    # Step 2 — verify TOTP (boundary-safe, one retry, clear diagnostics)
    request_key, _totp_err = _verify_totp_step(sess, BASE, request_key, totp_secret)
    if not request_key:
        return None, f"Step2 {_totp_err}"

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

# SILVERMIC trades only in these listed expiry months. Other tracked MCX
# contracts use the regular near-month symbol format.
_MCX_EXPIRY_MONTHS = {
    "SILVERMIC": (4, 6, 8, 11),  # Apr, Jun, Aug, Nov
}
_MCX_ROLLOVER_DAYS_BEFORE_EXPIRY = 5  # roll to next contract 5 days before expiry


def _active_mcx_expiry(symbol: str):
    """Return the selected MCX expiry date for the active/next contract."""
    import calendar
    from datetime import date, datetime, timezone, timedelta

    ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    today = ist.date()
    months = _MCX_EXPIRY_MONTHS.get(symbol, tuple(range(1, 13)))

    for year in (today.year, today.year + 1):
        for month in months:
            if year == today.year and month < today.month:
                continue
            last_day = calendar.monthrange(year, month)[1]
            expiry = date(year, month, last_day)
            rollover = expiry - timedelta(days=_MCX_ROLLOVER_DAYS_BEFORE_EXPIRY)
            if today < rollover:
                return expiry

    # Defensive fallback: first configured expiry in the following year.
    month = months[0]
    return date(today.year + 1, month, calendar.monthrange(today.year + 1, month)[1])


def _mcx_fyers_symbol(symbol: str) -> str:
    """
    Build the active near-month Fyers MCX symbol.
    Fyers format: MCX:SILVERMIC26APR  (symbol + 2-digit-year + 3-letter-month)
    Uses each commodity's listed expiry cycle and rolls shortly before expiry.
    """
    exp = _active_mcx_expiry(symbol)
    yy  = f"{exp.year % 100:02d}"       # "26"
    mmm = exp.strftime("%b").upper()    # "APR"
    return f"MCX:{symbol}{yy}{mmm}"


def get_quote(symbol: str, access_token: str) -> Optional[dict]:
    """
    Fetch live quote via Fyers API — NSE equities or MCX futures.
    Returns dict with: last_price, volume, change_pct, prev_close, high, low, open
    """
    try:
        fyers = get_fyers_model(access_token)
        if symbol in _MCX_SYMBOLS:
            # MCX futures quote symbols need the "FUT" suffix too (same as history).
            # Without it Fyers returns nothing and we silently fell back to yfinance,
            # so MCX-metal news quotes were never actually on the Fyers feed.
            fyers_sym = _mcx_fyers_symbol(symbol) + "FUT"
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


def get_history(symbol: str, access_token: str,
                resolution: str, range_from: str, range_to: str,
                cont_flag: int = 1) -> "pd.DataFrame":
    """
    Fetch OHLCV history from Fyers API.

    symbol:     internal symbol e.g. "SILVERMIC"
    resolution: "15" = 15m, "60" = 1H, "D" = daily
    range_from/to: "yyyy-mm-dd"
    cont_flag:  1 = continuous contract (use for MCX futures)

    Returns DataFrame with DatetimeIndex (UTC) and columns Open/High/Low/Close/Volume.
    Returns empty DataFrame on error.
    """
    import pandas as pd
    try:
        fyers = get_fyers_model(access_token)
        # MCX futures symbols require the "FUT" suffix (e.g. MCX:SILVERMIC26APRFUT)
        # for BOTH history and quotes.
        fyers_sym = (_mcx_fyers_symbol(symbol) + "FUT") if symbol in _MCX_SYMBOLS else f"NSE:{symbol}-EQ"
        resp = fyers.history({
            "symbol":      fyers_sym,
            "resolution":  resolution,
            "date_format": "1",
            "range_from":  range_from,
            "range_to":    range_to,
            "cont_flag":   str(cont_flag),
        })
        if resp.get("s") != "ok":
            return pd.DataFrame()
        candles = resp.get("candles", [])
        if not candles:
            return pd.DataFrame()
        # Candles are [ts, o, h, l, c, v] and MAY carry extra fields (Fyers added
        # open interest in Aug 2026, breaking a fixed 6-column parse) — take the
        # first 6 so schema additions can never kill history again.
        df = pd.DataFrame([c[:6] for c in candles],
                          columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        return df.set_index("timestamp")
    except Exception:
        return pd.DataFrame()
