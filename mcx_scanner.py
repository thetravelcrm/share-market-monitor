# ─────────────────────────────────────────────────────────────
#  mcx_scanner.py — cross-commodity calendar-spread opportunity scanner.
#
#  Runs the SAME rule that was built and validated on SILVERMIC across every liquid
#  MCX commodity, and ranks what it finds:
#      position% of the live spread inside its recent band  ->  CHEAP / FAIR / RICH
#      edge (distance to band mid)  ÷  real cost (both legs' bid-ask + charges)
#
#  Two deliberate design choices:
#
#  1. CONTRACTS COME FROM THE FYERS SYMBOL MASTER, not from guessed expiry months —
#     real symbols, real expiry dates, so no commodity needs a hand-maintained
#     calendar and newly listed contracts appear automatically.
#
#  2. BANDS COME FROM HISTORY, not from accumulation. The SILVERMIC tab builds its
#     band by sampling over days/weeks; here a rolling window of 15m history gives a
#     mature band on the FIRST scan, for every pair, and it can't be corrupted by a
#     lost state file.
#
#  Sizing note: MCX contract sizes (kg / barrels / mmBtu per lot) are NOT in the
#  symbol master and published sources disagree, so this module never guesses them.
#  Everything is per PRICE UNIT, and the ratio edge/cost is unit-free — which is what
#  ranking needs. ₹-per-lot is shown only for commodities in CONTRACT_UNITS below.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

_MASTER_URL = "https://public.fyers.in/sym_details/MCX_COM_sym_master.json"

# Liquid, multi-expiry commodities worth scanning by default.
LIQUID_DEFAULT = ["SILVERMIC", "GOLDM", "CRUDEOIL", "NATURALGAS", "COPPER", "ZINC"]
ALL_COMMODITIES = ["SILVERMIC", "SILVERM", "SILVER", "GOLDM", "GOLD",
                   "CRUDEOIL", "CRUDEOILM", "NATURALGAS",
                   "COPPER", "ZINC", "ALUMINIUM", "LEAD", "NICKEL"]

# Units per lot — ONLY entries verified against a real fill. SILVERMIC is 1 kg/lot,
# confirmed to the rupee against a live Fyers position. Add others yourself after
# checking your own contract note; anything absent shows as "per unit" instead of ₹.
CONTRACT_UNITS: dict[str, float] = {"SILVERMIC": 1.0}

# All-in round-trip charges as a % of the combined (both legs) notional: brokerage,
# CTT, exchange txn, stamp, GST. ~0.03% reproduces the ~₹130 we use for SILVERMIC.
CHARGE_RATE_PCT = 0.03

_master_cache: dict = {"day": None, "data": None}


def load_master(force: bool = False) -> dict:
    """Fyers MCX symbol master (cached per day). {} when unreachable."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not force and _master_cache["day"] == today and _master_cache["data"]:
        return _master_cache["data"]
    try:
        with urllib.request.urlopen(_MASTER_URL, timeout=30) as r:
            data = json.loads(r.read().decode())
        _master_cache.update({"day": today, "data": data})
        logger.info("MCX symbol master loaded: %d symbols", len(data))
        return data
    except Exception as e:
        logger.warning("symbol master fetch failed: %s", e)
        return _master_cache.get("data") or {}


def list_futures(commodity: str, min_dte: int = 11, limit: int = 4,
                 master: dict | None = None) -> list[dict]:
    """Live futures for one commodity, nearest first: [{symbol, expiry, dte}].
    Contracts inside `min_dte` days of expiry are dropped (safety buffer)."""
    master = master if master is not None else load_master()
    now = datetime.now(timezone.utc)
    out = []
    for sym, v in master.items():
        if v.get("underSym") != commodity or not sym.endswith("FUT"):
            continue
        try:
            exp = datetime.fromtimestamp(int(v["expiryDate"]), tz=timezone.utc)
        except Exception:
            continue
        dte = (exp - now).days
        if dte <= min_dte:
            continue
        out.append({"symbol": sym, "expiry": exp,
                    "label": exp.strftime("%b-%y"), "dte": dte})
    out.sort(key=lambda c: c["expiry"])
    return out[:limit]


def _history(token: str, symbol: str, days: int) -> pd.Series:
    """Closing series (15m) for one contract; empty Series when unavailable."""
    from silvermic_continuous import _fetch_one
    now = datetime.now(timezone.utc)
    df = _fetch_one(symbol, token, "15",
                    (now - timedelta(days=days + 5)).strftime("%Y-%m-%d"),
                    now.strftime("%Y-%m-%d"))
    if df is None or df.empty:
        return pd.Series(dtype=float)
    return df["Close"]


def _verdict(ratio: float) -> str:
    return "GOOD" if ratio >= 3.0 else ("THIN" if ratio >= 1.5 else "NO_EDGE")


def scan_commodity(token: str, commodity: str, lookback_days: int = 30,
                   min_dte: int = 11, charge_rate: float = CHARGE_RATE_PCT,
                   master: dict | None = None) -> list[dict]:
    """Every tradeable calendar pair for one commodity, scored. See scan()."""
    from silvermic_spread import quote_many
    contracts = list_futures(commodity, min_dte=min_dte, master=master)
    if len(contracts) < 2:
        return []

    quotes = quote_many([c["symbol"] for c in contracts], token)
    hist = {c["symbol"]: _history(token, c["symbol"], lookback_days) for c in contracts}

    rows = []
    for i in range(len(contracts)):
        for j in range(i + 1, len(contracts)):
            near, far = contracts[i], contracts[j]
            nq, fq = quotes.get(near["symbol"]) or {}, quotes.get(far["symbol"]) or {}
            n_px, f_px = nq.get("last_price", 0), fq.get("last_price", 0)
            if not (n_px and f_px):
                continue
            spread_now = f_px - n_px

            hn, hf = hist.get(near["symbol"]), hist.get(far["symbol"])
            if hn is None or hf is None or hn.empty or hf.empty:
                continue
            series = (hf - hn).dropna()          # aligns on shared 15m timestamps
            if len(series) < 50:
                continue
            band_min, band_max = float(series.min()), float(series.max())
            rng = band_max - band_min
            if rng <= 0:
                continue
            band_days = (series.index[-1] - series.index[0]).total_seconds() / 86400
            mid = (band_min + band_max) / 2
            pos = max(0.0, min(100.0, (spread_now - band_min) / rng * 100))
            edge = abs(spread_now - mid)

            # Real cost per price unit: cross both legs' books + all-in charges.
            widths = [q.get("ask", 0) - q.get("bid", 0) for q in (nq, fq)]
            book = sum(w for w in widths if w > 0)
            if not book or any(w <= 0 for w in widths):
                book = None                       # unknown book -> can't cost it
            cost = None if book is None else book + (n_px + f_px) * charge_rate / 100
            ratio = None if not cost else edge / cost

            if pos <= 25:
                bias, idea = "CHEAP", "LONG spread (buy far · sell near)"
            elif pos >= 75:
                bias, idea = "RICH", "SHORT spread (sell far · buy near)"
            else:
                bias, idea = "FAIR", "wait"
            units = CONTRACT_UNITS.get(commodity)
            rows.append({
                "commodity": commodity,
                "pair":      f"{far['label']} − {near['label']}",
                "near_sym":  near["symbol"], "far_sym": far["symbol"],
                "near_dte":  near["dte"],
                "spread":    round(spread_now, 2),
                "band_min":  round(band_min, 2), "band_max": round(band_max, 2),
                "band_days": round(band_days, 1),
                "pos":       round(pos),
                "bias":      bias,
                "edge":      round(edge, 2),
                "cost":      None if cost is None else round(cost, 2),
                "ratio":     None if ratio is None else round(ratio, 1),
                "verdict":   "UNKNOWN" if ratio is None else _verdict(ratio),
                "idea":      idea if bias != "FAIR" else "—",
                "units":     units,
                "edge_inr":  None if units is None else round(edge * units, 0),
                "cost_inr":  None if (units is None or cost is None) else round(cost * units, 0),
            })
    return rows


def scan(token: str, commodities: list[str] | None = None, lookback_days: int = 30,
         min_dte: int = 11, charge_rate: float = CHARGE_RATE_PCT,
         progress=None) -> list[dict]:
    """Scan several commodities and return every pair, best opportunity first
    (tradeable extremes with a payable edge rank above everything else)."""
    commodities = commodities or LIQUID_DEFAULT
    master = load_master()
    if not master:
        return []
    rows: list[dict] = []
    for n, c in enumerate(commodities, 1):
        if progress:
            progress(n / len(commodities), f"Scanning {c}… ({n}/{len(commodities)})")
        try:
            rows.extend(scan_commodity(token, c, lookback_days=lookback_days,
                                       min_dte=min_dte, charge_rate=charge_rate,
                                       master=master))
        except Exception as e:
            logger.warning("scan failed for %s: %s", c, e)
    rank = {"GOOD": 0, "THIN": 1, "NO_EDGE": 2, "UNKNOWN": 3}
    rows.sort(key=lambda r: (0 if r["bias"] in ("CHEAP", "RICH") else 1,
                             rank.get(r["verdict"], 9), -(r["ratio"] or 0)))
    return rows


def opportunities(rows: list[dict], min_ratio: float = 3.0) -> list[dict]:
    """Actionable subset: at a band extreme AND the edge pays its own friction."""
    return [r for r in rows
            if r["bias"] in ("CHEAP", "RICH") and (r["ratio"] or 0) >= min_ratio]


def alert_text(r: dict) -> str:
    inr = (f" (₹{r['edge_inr']:,.0f} edge / ₹{r['cost_inr']:,.0f} cost per lot)"
           if r.get("edge_inr") is not None else " per price unit")
    return (f"🔎 SPREAD OPPORTUNITY — {r['commodity']} {r['pair']}: {r['spread']:,.2f} "
            f"at {r['pos']}% of its {r['band_days']:.0f}d band ({r['bias']}) · "
            f"edge {r['ratio']}× cost{inr} → {r['idea']}")
