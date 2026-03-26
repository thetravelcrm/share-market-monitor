"""
fyers_auth.py  –  Run this LOCALLY once a day to get a fresh access token.

Usage:
    python fyers_auth.py

Then copy the printed access token into:
    Streamlit Cloud → your app → Settings → Secrets → FYERS_ACCESS_TOKEN
"""
import webbrowser
from fyers_apiv3 import fyersModel

# ── Fill these in ─────────────────────────────────────────────
CLIENT_ID     = input("Enter your Fyers Client ID (e.g. XXXXXXXX-100): ").strip()
SECRET_KEY    = input("Enter your Fyers Secret Key: ").strip()
REDIRECT_URI  = "https://arshadshare.streamlit.app"
# ─────────────────────────────────────────────────────────────

session = fyersModel.SessionModel(
    client_id=CLIENT_ID,
    secret_key=SECRET_KEY,
    redirect_uri=REDIRECT_URI,
    response_type="code",
    grant_type="authorization_code",
)

auth_url = session.generate_authcode()
print(f"\nOpening browser → log in with your Fyers account...")
webbrowser.open(auth_url)

print("\nAfter login you'll be redirected to your Streamlit app URL.")
print("Copy the 'auth_code' value from the URL bar.")
print("URL will look like: https://arshadshare.streamlit.app/?auth_code=XXXXX&state=None\n")

auth_code = input("Paste the auth_code here: ").strip()

session.set_token(auth_code)
resp = session.generate_token()

if resp.get("code") == 200:
    token = resp["access_token"]
    print(f"\n✅ Access Token (valid until midnight tonight):\n\n{token}\n")
    print("Add this to Streamlit Secrets as FYERS_ACCESS_TOKEN")
else:
    print(f"\n❌ Error: {resp}")
