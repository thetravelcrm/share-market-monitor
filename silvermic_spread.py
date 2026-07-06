# ─────────────────────────────────────────────────────────────
#  silvermic_spread.py — MCX SILVERMIC calendar-spread monitor.
#
#  Auto-detects the Zerodha-tradeable SILVERMIC contracts (expiry > 7 weeks /
#  49 days away — the near month is blocked near expiry), quotes them live via
#  Fyers, computes every pairwise spread (far − near, INR/kg), and tracks the
#  ALL-TIME min/max spread per pair (value + timestamp) in a GitHub gist so it
#  survives redeploys.
#
#  Per refresh the min/max is folded from the live spread (cheap, one quote call).
#  backfill() seeds/extends it from intraday history on demand.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import calendar
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta, date

# SILVERMIC expiry-month superset (Feb/Apr/Jun/Aug/Nov). Non-existent contracts
# simply don't quote on Fyers, so an extra candidate month is harmless.
_MONTHS = (2, 4, 6, 8, 11)
_IST = timezone(timedelta(hours=5, minutes=30))
_STATE_FILE = "silvermic_spread_state.json"
_TRADEABLE_MIN_DAYS = 49        # > 7 weeks to expiry == tradeable on Zerodha


def _ist_today() -> date:
    return datetime.now(_IST).date()


# ─────────────────────────────────────────────────────────────
#  Contract discovery
# ─────────────────────────────────────────────────────────────

def _candidate_contracts(today: date) -> list[dict]:
    """All upcoming SILVERMIC contracts (expiry = last calendar day of month)."""
    out: list[dict] = []
    for yr in (today.year, today.year + 1):
        for mo in _MONTHS:
            last = calendar.monthrange(yr, mo)[1]
            exp = date(yr, mo, last)
            if exp < today:
                continue
            mmm = exp.strftime("%b").upper()          # "AUG"
            yy = f"{yr % 100:02d}"                     # "26"
            # Fyers MCX futures use the FUT suffix for BOTH quotes and history.
            fut = f"MCX:SILVERMIC{yy}{mmm}FUT"
            out.append({
                "label":     f"{exp.strftime('%b')}-{yy}",   # "Aug-26"
                "quote_sym": fut,
                "hist_sym":  fut,
                "expiry":    exp.isoformat(),
                "dte":       (exp - today).days,
                "price":     0.0,
            })
    out.sort(key=lambda c: c["expiry"])
    return out[:4]    # only the nearest contracts are listed; bounds the quote calls


def _quote_val(v: dict) -> dict:
    lp = v.get("lp", 0)
    return {
        "last_price": float(lp),
        "prev_close": float(v.get("prev_close_price", lp) or lp),
        "high":       float(v.get("high_price", lp) or lp),
        "low":        float(v.get("low_price", lp) or lp),
        "volume":     int(v.get("volume", 0) or 0),
    }


def quote_many(quote_syms: list[str], token: str) -> dict[str, dict]:
    """
    Quote several Fyers symbols. Tries one batched call (mapping by the response's
    "n" field), then quotes any STILL-missing symbol individually and maps the result
    to the symbol WE queried (robust — does not depend on the response echoing "n").
    Skips unlisted/expired contracts that error. Returns {symbol: {last_price,…}}.
    """
    out: dict[str, dict] = {}
    if not quote_syms:
        return out
    try:
        from fyers_fetcher import get_fyers_model
        fyers = get_fyers_model(token)
        # 1. Batch (best effort) — map by the echoed symbol name when present.
        try:
            resp = fyers.quotes({"symbols": ",".join(quote_syms)})
            if resp.get("code") == 200:
                for item in resp.get("d", []) or []:
                    n = item.get("n", "")
                    v = item.get("v", {}) or {}
                    if n and v.get("lp", 0):
                        out[n] = _quote_val(v)
        except Exception:
            pass
        # 2. Per-symbol for anything still missing — map to the queried symbol.
        for s in [x for x in quote_syms if x not in out]:
            try:
                resp = fyers.quotes({"symbols": s})
                if resp.get("code") != 200:
                    continue
                d = resp.get("d") or []
                v = (d[0].get("v") if d else {}) or {}
                if v.get("lp", 0):
                    out[s] = _quote_val(v)   # assign to the symbol we asked for
            except Exception:
                continue
    except Exception:
        pass
    return out


def _last_price_from_history(token: str, hist_sym: str) -> float:
    """Latest traded price = most recent 15m candle close (Fyers history API, which
    works for MCX contracts even when fyers.quotes returns nothing)."""
    try:
        from silvermic_continuous import _fetch_one
        now = datetime.now(timezone.utc)
        df = _fetch_one(hist_sym, token, "15",
                        (now - timedelta(days=5)).strftime("%Y-%m-%d"),
                        now.strftime("%Y-%m-%d"))
        if df is not None and not df.empty:
            return float(df["Close"].iloc[-1])
    except Exception:
        pass
    return 0.0


def tradeable_contracts(token: str, min_days: int = _TRADEABLE_MIN_DAYS) -> list[dict]:
    """Tradeable SILVERMIC contracts: priced AND expiry > min_days away. Price comes
    from fyers.quotes if available, else the latest history candle (reliable for MCX)."""
    today = _ist_today()
    cands = [c for c in _candidate_contracts(today) if c["dte"] > min_days]
    quotes = quote_many([c["quote_sym"] for c in cands], token)
    out = []
    for c in cands:
        q = quotes.get(c["quote_sym"])
        price = q["last_price"] if (q and q["last_price"] > 0) else _last_price_from_history(token, c["hist_sym"])
        if price and price > 0:
            c["price"] = round(price, 2)
            out.append(c)
    out.sort(key=lambda c: c["expiry"])
    return out


def pairwise_spreads(contracts: list[dict]) -> list[dict]:
    """Every (near, far) pair. spread = far_price − near_price (INR/kg)."""
    spreads = []
    for i in range(len(contracts)):
        for j in range(i + 1, len(contracts)):
            near, far = contracts[i], contracts[j]    # sorted by expiry → i is nearer
            spreads.append({
                "key":        f"{near['quote_sym']}|{far['quote_sym']}",
                "label":      f"{far['label']} − {near['label']}",
                "near_label": near["label"],
                "far_label":  far["label"],
                "near_hist":  near["hist_sym"],
                "far_hist":   far["hist_sym"],
                "spread":     round(far["price"] - near["price"], 2),
            })
    return spreads


# ─────────────────────────────────────────────────────────────
#  All-time min/max persistence (gist + local fallback)
# ─────────────────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        import monitor_state
        s = monitor_state.load(_STATE_FILE)
        if s:
            return s
    except Exception:
        pass
    try:
        p = os.path.join(os.path.dirname(__file__), _STATE_FILE)
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_state(state: dict) -> None:
    try:
        import monitor_state
        monitor_state.save(state, _STATE_FILE)
    except Exception:
        pass
    try:                                  # local fallback (best-effort)
        p = os.path.join(os.path.dirname(__file__), _STATE_FILE)
        with open(p, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


def _fold(rec: dict, value: float, ts: str) -> None:
    if "min" not in rec or value < rec["min"]["value"]:
        rec["min"] = {"value": value, "ts": ts}
    if "max" not in rec or value > rec["max"]["value"]:
        rec["max"] = {"value": value, "ts": ts}


def _ist_date_of(ts_iso: str) -> str:
    """IST calendar date ('YYYY-MM-DD') of an ISO timestamp; '' if unparseable."""
    try:
        dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt.astimezone(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _fold_today(rec: dict, value: float, ts: str) -> None:
    """Track TODAY's (IST) session min/max separately — proof in the UI that the
    record is alive even when the all-time band doesn't move for days."""
    today = _ist_date_of(datetime.now(timezone.utc).isoformat())
    if _ist_date_of(ts) != today:
        return                       # historical fold from a previous day
    t = rec.get("today") or {}
    if t.get("date") != today:
        t = {"date": today}          # new session — reset
    if "min" not in t or value < t["min"]:
        t["min"] = value
    if "max" not in t or value > t["max"]:
        t["max"] = value
    rec["today"] = t


def _stamp_meta(state: dict, by: str) -> None:
    state["_meta"] = {"last_sample": datetime.now(timezone.utc).isoformat(), "by": by}


def update_and_get_minmax(spreads: list[dict]) -> dict:
    """Fold the current LIVE spread into the persisted all-time min/max. Cheap (no I/O
    to Fyers). Returns {key: {label, min:{value,ts}, max:{value,ts}, today:{…}}}."""
    state = _load_state()
    now_iso = datetime.now(timezone.utc).isoformat()
    for sp in spreads:
        rec = state.get(sp["key"]) or {}
        rec["label"] = sp["label"]
        _fold(rec, sp["spread"], now_iso)
        _fold_today(rec, sp["spread"], now_iso)
        state[sp["key"]] = rec
    _stamp_meta(state, "app")
    _save_state(state)
    return {sp["key"]: state[sp["key"]] for sp in spreads}


def last_sample_info() -> dict:
    """{'last_sample': iso, 'by': 'app'|'cron'} of the most recent record write."""
    return _load_state().get("_meta") or {}


def persisted_minmax() -> dict:
    """Read the stored all-time min/max (for display when the market is closed)."""
    return _load_state()


def cron_sample(token: str, hist_days: int = 2) -> int:
    """
    Headless sampler for the 24/7 cron: folds the live spread AND recent intraday
    history into the persisted all-time min/max (so extremes between cron runs are
    captured from the history bars). Returns the number of pairs updated.
    """
    contracts = tradeable_contracts(token)
    spreads = pairwise_spreads(contracts)
    if not spreads:
        return 0
    state = _load_state()
    now_iso = datetime.now(timezone.utc).isoformat()
    for sp in spreads:
        rec = state.get(sp["key"]) or {}
        rec["label"] = sp["label"]
        _fold(rec, sp["spread"], now_iso)
        _fold_today(rec, sp["spread"], now_iso)
        ext = _history_spread_extremes(token, sp["near_hist"], sp["far_hist"], hist_days)
        if ext:
            mn, mn_ts, mx, mx_ts = ext
            _fold(rec, mn, mn_ts)
            _fold(rec, mx, mx_ts)
            _fold_today(rec, mn, mn_ts)
            _fold_today(rec, mx, mx_ts)
        state[sp["key"]] = rec
    _stamp_meta(state, "cron")
    _save_state(state)
    return len(spreads)


# ─────────────────────────────────────────────────────────────
#  History-based extremes (for backfill / gap recapture)
# ─────────────────────────────────────────────────────────────

def _history_spread_extremes(token: str, near_hist: str, far_hist: str,
                             days: int, resolution: str = "15"):
    """(min, min_ts, max, max_ts) of (far.Close − near.Close) over `days` of history."""
    try:
        from silvermic_continuous import _fetch_one
        now = datetime.now(timezone.utc)
        d_to = now.strftime("%Y-%m-%d")
        d_from = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        a = _fetch_one(near_hist, token, resolution, d_from, d_to)
        b = _fetch_one(far_hist, token, resolution, d_from, d_to)
        if a.empty or b.empty:
            return None
        s = (b["Close"] - a["Close"]).dropna()   # aligns on shared timestamps
        if s.empty:
            return None
        mn_ts, mx_ts = s.idxmin(), s.idxmax()
        return (round(float(s.loc[mn_ts]), 2), mn_ts.isoformat(),
                round(float(s.loc[mx_ts]), 2), mx_ts.isoformat())
    except Exception:
        return None


def backfill(token: str, days: int = 30) -> dict:
    """Seed/extend the all-time min/max from `days` of intraday history."""
    contracts = tradeable_contracts(token)
    spreads = pairwise_spreads(contracts)
    state = _load_state()
    for sp in spreads:
        ext = _history_spread_extremes(token, sp["near_hist"], sp["far_hist"], days)
        if not ext:
            continue
        mn, mn_ts, mx, mx_ts = ext
        rec = state.get(sp["key"]) or {}
        rec["label"] = sp["label"]
        _fold(rec, mn, mn_ts)
        _fold(rec, mx, mx_ts)
        state[sp["key"]] = rec
    _save_state(state)
    return state


# ─────────────────────────────────────────────────────────────
#  Convenience for the UI
# ─────────────────────────────────────────────────────────────

def get_spread_board(token: str) -> tuple[list[dict], list[dict], dict]:
    """Return (tradeable_contracts, pairwise_spreads, minmax) — one Fyers quote call."""
    contracts = tradeable_contracts(token)
    spreads = pairwise_spreads(contracts)
    minmax = update_and_get_minmax(spreads) if spreads else {}
    return contracts, spreads, minmax


def debug_board(token: str) -> dict:
    """Diagnostics for the UI when no contracts resolve: what was tried, what came back."""
    cands = _candidate_contracts(_ist_today())
    quotes = quote_many([c["quote_sym"] for c in cands], token)
    return {
        "token_present": bool(token),
        "candidates":    [f"{c['label']} · {c['quote_sym']} · dte {c['dte']}" for c in cands],
        "quoted":        {k: v["last_price"] for k, v in quotes.items()},
        "tradeable":     [c["label"] for c in tradeable_contracts(token)],
    }


def fmt_ts_ist(iso: str) -> str:
    """Format a stored ISO-UTC timestamp as IST 'dd Mon HH:MM'."""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_IST).strftime("%d %b %H:%M")
    except Exception:
        return "—"
