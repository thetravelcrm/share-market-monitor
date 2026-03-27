# ─────────────────────────────────────────────────────────────
#  nse_data.py  –  NSE India market data (all free, no API key)
#  FII/DII flows, Bulk/Block deals, Corporate events, GIFT Nifty
#  All functions silent-fail → return None/[] on any error.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import requests
from datetime import datetime, timezone, timedelta
from typing import Optional

_SESSION = None   # reusable requests session with NSE cookies

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer":         "https://www.nseindia.com/",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
}


def _get_session() -> requests.Session:
    """Return a session that has visited NSE homepage (required for cookies)."""
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    s = requests.Session()
    s.headers.update(_HEADERS)
    try:
        s.get("https://www.nseindia.com/", timeout=10)
    except Exception:
        pass
    _SESSION = s
    return s


def _nse_get(path: str, timeout: int = 10) -> Optional[dict | list]:
    try:
        s    = _get_session()
        resp = s.get(f"https://www.nseindia.com/api/{path}", timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────
#  FII / DII daily flows
# ─────────────────────────────────────────────────────────────
def fetch_fii_dii() -> Optional[dict]:
    """
    Returns today's FII and DII net buy/sell in crore INR.
    {fii_buy, fii_sell, fii_net, dii_buy, dii_sell, dii_net, date, sentiment}
    """
    data = _nse_get("fiidiiTradeReact")
    if not data:
        return None
    try:
        # NSE returns a list; last entry is most recent
        row = data[-1] if isinstance(data, list) else data
        fii_buy  = float(str(row.get("fiiBuy",  "0")).replace(",", ""))
        fii_sell = float(str(row.get("fiiSell", "0")).replace(",", ""))
        dii_buy  = float(str(row.get("diiBuy",  "0")).replace(",", ""))
        dii_sell = float(str(row.get("diiSell", "0")).replace(",", ""))
        fii_net  = round(fii_buy - fii_sell, 2)
        dii_net  = round(dii_buy - dii_sell, 2)
        sentiment = "Bullish" if fii_net > 0 else "Bearish"
        return {
            "fii_buy":  fii_buy,  "fii_sell": fii_sell, "fii_net": fii_net,
            "dii_buy":  dii_buy,  "dii_sell": dii_sell, "dii_net": dii_net,
            "date":     row.get("date", ""),
            "sentiment": sentiment,
        }
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
#  Bulk Deals
# ─────────────────────────────────────────────────────────────
def fetch_bulk_deals() -> list[dict]:
    """
    Returns list of today's bulk deals.
    Each: {symbol, name, client, buy_sell, qty, price, exchange}
    """
    data = _nse_get("bulk-deals")
    if not data:
        return []
    try:
        deals = data if isinstance(data, list) else data.get("data", [])
        result = []
        for d in deals[:50]:
            result.append({
                "symbol":    d.get("symbol", ""),
                "name":      d.get("sName",  d.get("companyName", "")),
                "client":    d.get("clientName", ""),
                "buy_sell":  d.get("buySell", ""),
                "qty":       int(str(d.get("quantityTraded", "0")).replace(",", "") or 0),
                "price":     float(str(d.get("tradePrice", "0")).replace(",", "") or 0),
                "exchange":  "NSE",
            })
        return result
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
#  Block Deals
# ─────────────────────────────────────────────────────────────
def fetch_block_deals() -> list[dict]:
    """
    Returns list of today's block deals.
    Each: {symbol, name, client, buy_sell, qty, price}
    """
    data = _nse_get("block-deals")
    if not data:
        return []
    try:
        deals = data if isinstance(data, list) else data.get("data", [])
        result = []
        for d in deals[:50]:
            result.append({
                "symbol":   d.get("symbol", ""),
                "name":     d.get("sName", d.get("companyName", "")),
                "client":   d.get("clientName", ""),
                "buy_sell": d.get("buySell", ""),
                "qty":      int(str(d.get("quantityTraded", "0")).replace(",", "") or 0),
                "price":    float(str(d.get("tradePrice", "0")).replace(",", "") or 0),
            })
        return result
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
#  Corporate Events (earnings, board meetings, dividends)
# ─────────────────────────────────────────────────────────────
def fetch_corporate_events(days_ahead: int = 7) -> list[dict]:
    """
    Returns upcoming corporate events within `days_ahead` days.
    Each: {symbol, company, purpose, ex_date, days_away}
    Filters to: Board Meeting, Results, Dividend, AGM, Bonus, Split
    """
    data = _nse_get("event-calendar")
    if not data:
        return []
    try:
        events = data if isinstance(data, list) else data.get("data", [])
        today  = datetime.now(tz=timezone.utc).date()
        cutoff = today + timedelta(days=days_ahead)
        _IMPORTANT = {"board meeting", "results", "dividend", "agm", "annual general meeting",
                      "bonus", "split", "stock split", "rights", "earnings"}
        result = []
        for e in events:
            purpose = str(e.get("purpose", "") or e.get("bm_desc", "")).lower()
            if not any(kw in purpose for kw in _IMPORTANT):
                continue
            raw_date = e.get("bm_date") or e.get("date") or ""
            try:
                ex_date = datetime.strptime(raw_date[:10], "%d-%b-%Y").date()
            except Exception:
                try:
                    ex_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
                except Exception:
                    continue
            if today <= ex_date <= cutoff:
                days_away = (ex_date - today).days
                result.append({
                    "symbol":    e.get("symbol", ""),
                    "company":   e.get("companyName", e.get("company", "")),
                    "purpose":   e.get("purpose", e.get("bm_desc", "")),
                    "ex_date":   ex_date.strftime("%d %b %Y"),
                    "days_away": days_away,
                })
        result.sort(key=lambda x: x["days_away"])
        return result
    except Exception:
        return []


def get_events_for_symbol(symbol: str, events: list[dict]) -> list[dict]:
    """Filter corporate events list to a specific symbol."""
    return [e for e in events if e.get("symbol", "").upper() == symbol.upper()]


# ─────────────────────────────────────────────────────────────
#  GIFT Nifty (pre-market indicator)
# ─────────────────────────────────────────────────────────────
def fetch_gift_nifty() -> Optional[dict]:
    """
    Returns GIFT Nifty level and its premium/discount to NSE Nifty.
    Uses Yahoo Finance: ^NSEI for spot Nifty, yfinance for GIFT Nifty proxy.
    """
    try:
        import yfinance as yf

        # Regular NSE Nifty (delayed)
        nsei = yf.Ticker("^NSEI")
        nsei_hist = nsei.history(period="2d", interval="1d", auto_adjust=True)
        if nsei_hist.empty:
            return None
        nifty_close = float(nsei_hist["Close"].iloc[-1])
        nifty_prev  = float(nsei_hist["Close"].iloc[-2]) if len(nsei_hist) >= 2 else nifty_close
        nifty_chg   = round((nifty_close - nifty_prev) / nifty_prev * 100, 2)

        # GIFT Nifty futures — Yahoo Finance uses "NIFTY50.NS" futures or ^CNXIT
        # Best proxy available freely: SGX Nifty via CME (NIFTY Futures may not be in yf)
        # Use Nifty 50 itself as reference; show last known close
        return {
            "nifty_close":  round(nifty_close, 2),
            "nifty_change": nifty_chg,
            "gift_level":   None,    # Real GIFT Nifty requires paid feed
            "premium":      None,
            "source":       "NSE Nifty (^NSEI)",
        }
    except Exception:
        return None
