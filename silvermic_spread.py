# ─────────────────────────────────────────────────────────────
#  silvermic_spread.py — MCX SILVERMIC calendar-spread monitor.
#
#  Auto-detects the Zerodha-tradeable SILVERMIC contracts (expiry > 1 week away —
#  Zerodha blocks new MCX positions in the final week), quotes them live via
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
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta, date

# SILVERMIC expiry-month superset (Feb/Apr/Jun/Aug/Nov). Non-existent contracts
# simply don't quote on Fyers, so an extra candidate month is harmless.
_MONTHS = (2, 4, 6, 8, 11)
_IST = timezone(timedelta(hours=5, minutes=30))
_STATE_FILE = "silvermic_spread_state.json"
# Zerodha blocks new MCX positions in the final week before expiry; we drop the near
# contract a few days EARLIER as a safety buffer (user rule: Aug-26 expiring 31 Aug
# leaves the board on 20 Aug -> dte 11). The next contract auto-joins the 3-slot board.
_TRADEABLE_MIN_DAYS = 11


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
        # Best bid/offer — the ACTUAL exit prices (LTP is just the last trade; on
        # thin far months your real close happens at bid (sell) / ask (buy back)).
        "bid":        float(v.get("bid", 0) or 0),
        "ask":        float(v.get("ask", 0) or 0),
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
            # live book (0 when unavailable, e.g. history-fallback pricing)
            c["bid"] = float(q.get("bid", 0) or 0) if q else 0.0
            c["ask"] = float(q.get("ask", 0) or 0) if q else 0.0
            out.append(c)
    out.sort(key=lambda c: c["expiry"])
    out = out[:4]
    # fyers.quotes often returns no bid/ask for MCX, which leaves every row costed
    # as "book unknown". The depth endpoint always has the ladder, so use it to fill
    # the touch for anything the quote didn't price.
    missing = [c["quote_sym"] for c in out if not (c["bid"] and c["ask"])]
    if missing:
        try:
            from fyers_fetcher import get_depth
            dep = get_depth(missing, token)
            for c in out:
                d = dep.get(c["quote_sym"])
                if d and d.get("bids") and d.get("asks"):
                    c["bid"] = float(d["bids"][0]["price"])
                    c["ask"] = float(d["asks"][0]["price"])
        except Exception as e:
            _slog.warning("depth fallback for bid/ask failed: %s", e)
    # ALL Zerodha-tradeable contracts (up to the 4 live expiries). The near leg
    # drops at dte<=_TRADEABLE_MIN_DAYS (safety buffer before Zerodha's final-week
    # block); illiquid far-pair combos are handled by the Cost-vs-Edge gate, which
    # marks them unpayable rather than hiding them.
    return out


def pairwise_spreads(contracts: list[dict]) -> list[dict]:
    """Every (near, far) pair. spread = far_price − near_price (INR/kg)."""
    spreads = []
    for i in range(len(contracts)):
        for j in range(i + 1, len(contracts)):
            near, far = contracts[i], contracts[j]    # sorted by expiry → i is nearer
            sp = {
                "key":        f"{near['quote_sym']}|{far['quote_sym']}",
                "label":      f"{far['label']} − {near['label']}",
                "near_label": near["label"],
                "far_label":  far["label"],
                "near_hist":  near["hist_sym"],
                "far_hist":   far["hist_sym"],
                "spread":     round(far["price"] - near["price"], 2),
            }
            # Round-trip BOOK cost of trading this spread (enter + exit both legs at
            # the touch) = full bid-ask width of each leg. 0/absent when book unknown.
            if all(near.get(k, 0) > 0 for k in ("bid", "ask")) and \
               all(far.get(k, 0) > 0 for k in ("bid", "ask")):
                sp["book_cost"] = round((far["ask"] - far["bid"]) + (near["ask"] - near["bid"]), 2)
                try:      # exact charges (contract-note verified), 1 kg/lot
                    import mcx_costs as _mcc
                    sp["charges"] = round(
                        _mcc.spread_round_trip_charges(near["price"], far["price"]), 2)
                except Exception:
                    pass
            spreads.append(sp)
    return spreads


def pair_symbols(min_days: int = _TRADEABLE_MIN_DAYS) -> list[dict]:
    """Tradeable pairs (label + both history symbols) WITHOUT any quote call, so the
    backtest works when the market is closed."""
    cands = [c for c in _candidate_contracts(_ist_today()) if c["dte"] > min_days][:4]
    out = []
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            near, far = cands[i], cands[j]
            out.append({"label":     f"{far['label']} − {near['label']}",
                        "near_hist": near["hist_sym"],
                        "far_hist":  far["hist_sym"]})
    return out


def spread_history_daily(token: str, near_hist: str, far_hist: str,
                         days: int = 7) -> list[dict]:
    """Daily spread stats [{date, min, max, last}] from 15m history of both legs
    (inner-aligned on bar timestamp). Real data for the AI band-quality check —
    empty list when history is unavailable."""
    try:
        import time as _t
        import pandas as pd
        from silvermic_continuous import _fetch_one
        now = datetime.now(timezone.utc)
        d_from = (now - timedelta(days=days + 3)).strftime("%Y-%m-%d")
        d_to   = now.strftime("%Y-%m-%d")

        import logging
        _log = logging.getLogger("silvermic_spread")

        def _fetch_retry(sym):
            # One retry after a short pause — a fragment run fires several Fyers
            # calls back-to-back and a single leg can transiently return no bars.
            df = _fetch_one(sym, token, "15", d_from, d_to)
            if df is None or df.empty:
                _t.sleep(1.0)
                df = _fetch_one(sym, token, "15", d_from, d_to)
            if df is None or df.empty:
                _log.warning("spread_history_daily: %s returned no 15m bars (%s..%s)",
                             sym, d_from, d_to)
            return df

        n = _fetch_retry(near_hist)
        f = _fetch_retry(far_hist)
        if n is None or f is None or n.empty or f.empty:
            return []
        _log.info("spread_history_daily: %s=%d bars, %s=%d bars",
                  near_hist, len(n), far_hist, len(f))
        sp = (f["Close"] - n["Close"]).dropna()          # aligns on shared bars
        if sp.empty:
            return []
        ist_dates = (sp.index + pd.Timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        df = pd.DataFrame({"spread": sp.values, "date": ist_dates})
        out = [{"date": d,
                "min":  round(float(g["spread"].min())),
                "max":  round(float(g["spread"].max())),
                "last": round(float(g["spread"].iloc[-1]))}
               for d, g in df.groupby("date", sort=True)]
        return out[-days:]
    except Exception:
        return []


# Estimated statutory + brokerage cost per lot-pair ROUND TRIP (Zerodha ₹20 × 4
# orders + CTT on the two sells + exchange/txn charges + GST at SILVERMIC notionals
# ≈ ₹220k/leg). An estimate, not a quote — refine against your contract notes.
EST_CHARGES_RT = 130.0


# A band younger than this isn't a mean-reversion range yet — it's just the recent
# swing. Position % against it is noise, so a trade on it isn't a real candidate.
MIN_BAND_DAYS = 5.0


def band_age_days(rec: dict) -> float | None:
    """How long the stored band has been accumulating: now − the OLDEST extreme
    timestamp, in days. None when the record has no usable timestamps."""
    stamps = []
    for side in ("min", "max"):
        ts = (rec.get(side) or {}).get("ts")
        if ts:
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                stamps.append(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))
            except Exception:
                pass
    if not stamps:
        return None
    return max(0.0, (datetime.now(timezone.utc) - min(stamps)).total_seconds() / 86400)


def trade_worth_check(spread_now: float, book_cost: float | None,
                      band_min: float | None, band_max: float | None,
                      charges: float | None = None) -> dict:
    """Is a mean-reversion trade on this pair worth its friction RIGHT NOW?

    Expected capture = distance from the current spread to the band midpoint (the
    mean-reversion target). Total round-trip cost = live book cost + EST_CHARGES_RT.
    Rule of thumb: take the trade only when capture ≥ 3× cost.

    Returns {edge, cost, ratio, verdict: 'GOOD'|'THIN'|'NO_EDGE'|'UNKNOWN'}."""
    if book_cost is None or band_min is None or band_max is None or band_max <= band_min:
        return {"verdict": "UNKNOWN"}
    cost = book_cost + (EST_CHARGES_RT if charges is None else charges)
    mid  = (band_min + band_max) / 2
    edge = abs(spread_now - mid)
    ratio = edge / cost if cost > 0 else 0.0
    if ratio >= 3.0:
        verdict = "GOOD"
    elif ratio >= 1.5:
        verdict = "THIN"
    else:
        verdict = "NO_EDGE"
    return {"edge": round(edge, 2), "cost": round(cost, 2),
            "ratio": round(ratio, 1), "verdict": verdict}


# ─────────────────────────────────────────────────────────────
#  All-time min/max persistence (gist + local fallback)
# ─────────────────────────────────────────────────────────────

import logging
_slog = logging.getLogger("silvermic_spread")


# True when the last _load_state() could not read the gist. A blind save after a
# failed load would overwrite the accumulated all-time band with a single fresh
# sample — that is how the bands got reset to one day old.
_LOAD_FAILED = False


def _load_state() -> dict:
    global _LOAD_FAILED
    _LOAD_FAILED = False
    try:
        import monitor_state
        s = monitor_state.load(_STATE_FILE)
        if s:
            return s
        # Empty result: genuinely-empty gist vs failed read are indistinguishable
        # unless monitor_state says so.
        _LOAD_FAILED = bool(getattr(monitor_state, "LAST_LOAD_FAILED", False))
    except Exception as e:
        _LOAD_FAILED = True
        _slog.warning("gist state load failed (%s) — trying local fallback", e)
    try:
        p = os.path.join(os.path.dirname(__file__), _STATE_FILE)
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    except Exception as e:
        _slog.warning("local state load failed: %s", e)
    return {}


def _merge_states(remote: dict, local: dict) -> dict:
    """Fold `local` onto `remote` without losing history: band records keep the TRUE
    extremes from both sides; config/meta keys prefer the newer local value."""
    out = dict(remote)
    for key, rec in local.items():
        if key.startswith("_") or not isinstance(rec, dict):
            out[key] = rec                       # _alerts/_pnl/_meta: local wins
            continue
        base = dict(out.get(key) or {})
        base.update({k: v for k, v in rec.items() if k not in ("min", "max")})
        for side, better in (("min", min), ("max", max)):
            r, l = (out.get(key) or {}).get(side), rec.get(side)
            if r and l:
                base[side] = r if better(r["value"], l["value"]) == r["value"] else l
            else:
                base[side] = l or r
        out[key] = base
    return out


def _save_state(state: dict, keep_config: bool = True) -> None:
    """Persist the shared state.

    `keep_config=True` (the default) re-reads the CURRENTLY stored alert config just
    before writing and keeps it. The app, the 5s watcher and the cron all write this
    one gist file: a writer loads state, spends minutes folding min/max, then saves
    the whole file — silently reverting any alert level the user set in between. That
    is why alerts appeared not to survive. Routine writers now never carry a stale
    config over the live one; set_alert_config/set_pnl_alert pass keep_config=False
    because they ARE the authority for those keys."""
    try:
        import monitor_state
        if keep_config:
            try:
                fresh = monitor_state.load(_STATE_FILE)
                if fresh:
                    for k in ("_alerts", "_pnl"):
                        if fresh.get(k) is not None:
                            state[k] = fresh[k]
            except Exception as e:
                _slog.warning("could not refresh alert config before save: %s", e)
        if _LOAD_FAILED:
            # Don't clobber the stored band with a state built from nothing: re-read
            # once and merge; if that read also fails, skip the gist write entirely.
            remote = monitor_state.load(_STATE_FILE)
            if remote:
                state = _merge_states(remote, state)
                _slog.warning("state save after failed load — merged with gist "
                              "instead of overwriting")
            elif getattr(monitor_state, "LAST_LOAD_FAILED", False):
                _slog.error("gist unreadable — SKIPPING save to protect stored band")
                raise RuntimeError("gist unreadable; save skipped")
        monitor_state.save(state, _STATE_FILE)
    except Exception as e:
        # Alert dedup + min/max sharing depend on the gist — a persistent failure
        # here means app/cron/watcher stop seeing each other's flags.
        _slog.warning("gist state save failed: %s", e)
    try:                                  # local fallback (best-effort)
        p = os.path.join(os.path.dirname(__file__), _STATE_FILE)
        with open(p, "w") as f:
            json.dump(state, f)
    except Exception as e:
        _slog.warning("local state save failed: %s", e)


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


# ─────────────────────────────────────────────────────────────
#  Threshold alerts — per pair High/Low, once per crossing.
#  Config AND fired-flags live in the shared gist state, so the app (60s) and the
#  24/7 cron (~20 min) watch the same levels and never double-alert.
# ─────────────────────────────────────────────────────────────

def get_alert_config() -> dict:
    """{pair_key: {"high": float|None, "low": float|None, fired_…, saved_at}}."""
    return _load_state().get("_alerts") or {}


def active_alerts() -> list[dict]:
    """Every level currently stored, for display — so the user can SEE that alerts
    survived rather than having to trust it."""
    out = []
    for key, c in (get_alert_config() or {}).items():
        if c.get("high") is None and c.get("low") is None:
            continue
        near = key.split("|")[0]
        far = key.split("|")[-1]
        out.append({
            "commodity": commodity_of(near) or "?",
            "pair":      f"{contract_label(far)} − {contract_label(near)}",
            "low":       c.get("low"), "high": c.get("high"),
            "saved_at":  c.get("saved_at", ""),
        })
    return sorted(out, key=lambda r: (r["commodity"], r["pair"]))


def set_alert_config(cfg: dict) -> None:
    """Save per-pair thresholds {key: {"high":…, "low":…}} (None = side not watched).
    A pair whose levels changed gets its fired flags reset so new levels re-arm."""
    state = _load_state()
    alerts = state.get("_alerts") or {}
    for key, c in cfg.items():
        prev = alerts.get(key) or {}
        entry = {**prev, "high": c.get("high"), "low": c.get("low")}
        if prev.get("high") != c.get("high") or prev.get("low") != c.get("low"):
            entry["fired_high"] = False
            entry["fired_low"]  = False
        entry["saved_at"] = datetime.now(timezone.utc).isoformat()
        alerts[key] = entry
    state["_alerts"] = alerts
    _save_state(state, keep_config=False)      # this call IS the authority


def check_spread_alerts(spreads: list[dict]) -> list[dict]:
    """Compare live spreads to the saved thresholds. Fires ONCE per crossing: a side
    that fired re-arms only after the spread comes back inside the band. Fired flags
    are persisted immediately (before the Slack send), so a failed send is reported
    by the caller rather than retried into spam.
    Returns [{label, side: 'HIGH'|'LOW', level, value}] for sides that just crossed."""
    state = _load_state()
    alerts = state.get("_alerts") or {}
    if not alerts:
        return []
    events, dirty = [], False
    for sp in spreads:
        c = alerts.get(sp["key"])
        if not c:
            continue
        val = sp["spread"]
        hi, lo = c.get("high"), c.get("low")
        if hi is not None:
            if val >= hi and not c.get("fired_high"):
                c["fired_high"] = True; dirty = True
                events.append({"label": sp["label"], "side": "HIGH", "level": hi,
                               "value": val, "commodity": commodity_of(sp["key"].split("|")[0])})
            elif val < hi and c.get("fired_high"):
                c["fired_high"] = False; dirty = True      # back inside → re-armed
        if lo is not None:
            if val <= lo and not c.get("fired_low"):
                c["fired_low"] = True; dirty = True
                events.append({"label": sp["label"], "side": "LOW", "level": lo,
                               "value": val, "commodity": commodity_of(sp["key"].split("|")[0])})
            elif val > lo and c.get("fired_low"):
                c["fired_low"] = False; dirty = True
    if dirty:
        state["_alerts"] = alerts
        _save_state(state)
    return events


# ─────────────────────────────────────────────────────────────
#  Live Fyers positions → spread pairs + P&L alerts
# ─────────────────────────────────────────────────────────────

_FUT_RE = re.compile(r"MCX:([A-Z][A-Z0-9]*?)(\d\d)([A-Z]{3})FUT$")
_MON_NUM = {m.upper(): i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def contract_label(symbol: str) -> str:
    """'MCX:SILVERMIC27FEBFUT' -> 'Feb-27' (unknown formats pass through)."""
    m = _FUT_RE.match(symbol or "")
    return f"{m.group(3).title()}-{m.group(2)}" if m else (symbol or "")


def commodity_of(symbol: str) -> str:
    """'MCX:SILVER10026AUGFUT' -> 'SILVER100' ('' if unparseable)."""
    m = _FUT_RE.match(symbol or "")
    return m.group(1) if m else ""


def _sym_order(symbol: str) -> tuple:
    """Sortable (year, month) of an MCX FUT symbol; far month sorts later."""
    m = _FUT_RE.match(symbol or "")
    if not m:
        return (99, 99)
    return (int(m.group(2)), _MON_NUM.get(m.group(3), 99))


def detect_position_spreads(positions: list[dict], quotes: dict | None = None) -> list[dict]:
    """Find SILVERMIC calendar-spread pairs among live positions: a LONG and a SHORT
    SILVERMIC FUT held together. Returns [{label, side, lots, entry_spread,
    live_spread, pnl}] — side is the SPREAD's side (LONG spread = long the far leg).
    SILVERMIC = 1 kg/lot, so spread ₹/kg × lots = ₹ P&L.

    When `quotes` ({symbol: {bid, ask}}) is given, each pair also gets the EXECUTABLE
    close: exit_spread/exec_pnl computed at the touch — long legs sell at BID, short
    legs buy back at ASK — i.e. the P&L you'd actually realize crossing the book now."""
    sil = [p for p in positions
           if _FUT_RE.match(p.get("symbol", "")) and "SILVERMIC" in p.get("symbol", "")
           and p.get("net_qty")]
    longs  = sorted([p for p in sil if p["net_qty"] > 0], key=lambda p: _sym_order(p["symbol"]))
    shorts = sorted([p for p in sil if p["net_qty"] < 0], key=lambda p: _sym_order(p["symbol"]))
    pairs = []
    for lp in longs:
        for sp in shorts:
            lots = min(lp["net_qty"], -sp["net_qty"])
            if lots <= 0:
                continue
            near, far = sorted([lp, sp], key=lambda p: _sym_order(p["symbol"]))
            if near["symbol"] == far["symbol"]:
                continue
            entry = far["avg"] - near["avg"]
            live  = far["ltp"] - near["ltp"]
            long_spread = far["net_qty"] > 0          # long far leg == LONG the spread
            pnl = (live - entry if long_spread else entry - live) * lots
            pair = {
                "label":        f"{contract_label(far['symbol'])} − {contract_label(near['symbol'])}",
                "side":         "LONG" if long_spread else "SHORT",
                "lots":         lots,
                "entry_spread": round(entry, 2),
                "live_spread":  round(live, 2),
                "pnl":          round(pnl, 2),
            }
            if quotes:
                fq = quotes.get(far["symbol"]) or {}
                nq = quotes.get(near["symbol"]) or {}
                if long_spread:
                    # close = sell far at bid, buy near back at ask
                    f_px, n_px = fq.get("bid", 0), nq.get("ask", 0)
                else:
                    # close = buy far back at ask, sell near at bid
                    f_px, n_px = fq.get("ask", 0), nq.get("bid", 0)
                if f_px and n_px:
                    exit_spread = f_px - n_px
                    exec_pnl = (exit_spread - entry if long_spread else entry - exit_spread) * lots
                    pair["exit_spread"] = round(exit_spread, 2)
                    pair["exec_pnl"]    = round(exec_pnl, 2)
            pairs.append(pair)
    return pairs


def get_pnl_alert() -> dict:
    """{'profit': float|None, 'loss': float|None, fired flags} — loss stored positive."""
    return _load_state().get("_pnl") or {}


def set_pnl_alert(profit, loss) -> None:
    """Save total-P&L alert levels (None = side off). Changed levels re-arm."""
    state = _load_state()
    prev = state.get("_pnl") or {}
    entry = {**prev, "profit": profit, "loss": loss}
    if prev.get("profit") != profit or prev.get("loss") != loss:
        entry["fired_profit"] = False
        entry["fired_loss"]   = False
    entry["saved_at"] = datetime.now(timezone.utc).isoformat()
    state["_pnl"] = entry
    _save_state(state, keep_config=False)      # this call IS the authority


def check_pnl_alert(total_pl: float) -> list[dict]:
    """Once-per-crossing check of total live P&L vs the saved levels (same semantics
    as the spread alerts; flags persist in the shared gist for app/watcher dedup)."""
    state = _load_state()
    c = state.get("_pnl")
    if not c:
        return []
    events, dirty = [], False
    profit, loss = c.get("profit"), c.get("loss")
    if profit is not None:
        if total_pl >= profit and not c.get("fired_profit"):
            c["fired_profit"] = True; dirty = True
            events.append({"side": "PROFIT", "level": profit, "value": total_pl})
        elif total_pl < profit and c.get("fired_profit"):
            c["fired_profit"] = False; dirty = True
    if loss is not None:
        if total_pl <= -loss and not c.get("fired_loss"):
            c["fired_loss"] = True; dirty = True
            events.append({"side": "LOSS", "level": -loss, "value": total_pl})
        elif total_pl > -loss and c.get("fired_loss"):
            c["fired_loss"] = False; dirty = True
    if dirty:
        state["_pnl"] = c
        _save_state(state)
    return events


def pnl_alert_text(ev: dict) -> str:
    if ev["side"] == "PROFIT":
        return (f"💰 P&L ALERT — your live Fyers positions are up ₹{ev['value']:,.0f} "
                f"(target ₹{ev['level']:,.0f} hit). Consider booking/trailing.")
    return (f"🛑 P&L ALERT — your live Fyers positions are down ₹{abs(ev['value']):,.0f} "
            f"(limit ₹{abs(ev['level']):,.0f} hit). Check your stop discipline.")


def watcher_persist(pending: dict) -> None:
    """Fold locally-accumulated extremes {key: {label, min:(v,ts), max:(v,ts)}} into
    the persisted record in ONE gist write. spread_watcher samples every ~5s but
    calls this only every few minutes, so the gist API isn't hammered."""
    if not pending:
        return
    state = _load_state()
    for key, p in pending.items():
        rec = state.get(key) or {}
        rec["label"] = p["label"]
        for v, ts in (p["min"], p["max"]):
            _fold(rec, v, ts)
            _fold_today(rec, v, ts)
        state[key] = rec
    _stamp_meta(state, "watch")
    _save_state(state)


def alert_symbols() -> list[tuple[str, str, str]]:
    """[(key, near_sym, far_sym)] for every pair that currently has a level set —
    lets the 5s watcher follow scanner pairs (SILVER100, CRUDEOILM…) too, not just
    SILVERMIC, since alert keys are already "<near>|<far>" symbol pairs."""
    out = []
    for key, c in (get_alert_config() or {}).items():
        if c.get("high") is None and c.get("low") is None:
            continue
        parts = key.split("|")
        if len(parts) == 2 and parts[0].startswith("MCX:"):
            out.append((key, parts[0], parts[1]))
    return out


def alert_text(ev: dict) -> str:
    """Slack message for a crossing event (shared by app + cron)."""
    dirn = "ABOVE" if ev["side"] == "HIGH" else "BELOW"
    hint = ("RICH — idea: SHORT spread (sell far · buy near)" if ev["side"] == "HIGH"
            else "CHEAP — idea: LONG spread (buy far · sell near)")
    com = ev.get("commodity") or "SILVERMIC"
    fmt = ",.2f" if abs(ev["value"]) < 1000 else ",.0f"    # small spreads need decimals
    return (f"📐 SPREAD ALERT — {com} {ev['label']}: ₹{ev['value']:{fmt}} crossed "
            f"{dirn} your ₹{ev['level']:{fmt}} · {hint}")


def persisted_minmax() -> dict:
    """Read the stored all-time min/max (for display when the market is closed)."""
    return _load_state()


def cron_sample(token: str, hist_days: int = 2) -> list[dict]:
    """
    Headless sampler for the 24/7 cron: folds the live spread AND recent intraday
    history into the persisted all-time min/max (so extremes between cron runs are
    captured from the history bars). Returns the sampled spreads (empty when none),
    so the caller can run the threshold-alert check on them.
    """
    contracts = tradeable_contracts(token)
    spreads = pairwise_spreads(contracts)
    if not spreads:
        return []
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
    return spreads


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
