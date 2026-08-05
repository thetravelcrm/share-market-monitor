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
#  3. SIZING AND CAPITAL come from Zerodha's own margin calculator (zerodha_margins):
#     the ₹ multiplier per lot is derived exactly from margin = rate × price × mult,
#     and the NRML margin gives capital required. That turns the ranking into RETURN
#     ON MARGIN — the only fair way to compare a ₹30k-margin silver spread against a
#     ₹450k-margin crude spread.
#
#  SILVERMIC is intentionally excluded: it has its own tab.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone, timedelta

import pandas as pd

import mcx_costs as _mcc
import zerodha_margins as _zm

logger = logging.getLogger(__name__)

_MASTER_URL = "https://public.fyers.in/sym_details/MCX_COM_sym_master.json"

# Most MCX contracts need lakhs of margin per leg. These are the MINI contracts —
# same underlying, small lot — whose single-leg NRML margin fits a retail budget and
# which still have enough listed expiries for calendar spreads. SILVERMIC (₹29.8k,
# the cheapest of all) is deliberately absent: it has its own dedicated tab.
MARGIN_BUDGET_DEFAULT = 40_000.0

# Affordable AND reasonably liquid — the sensible default scan set.
LIQUID_DEFAULT = ["SILVER100", "CRUDEOILM", "NATGASMINI", "LEADMINI",
                  "GOLDTEN", "ZINCMINI", "ALUMINI"]

# Everything worth offering; the margin budget decides what actually gets scanned.
# (Thin/seasonal ones like GOLDPETAL, STEELREBAR, KAPAS are selectable but not default.)
ALL_COMMODITIES = ["SILVER100", "CRUDEOILM", "NATGASMINI", "ZINCMINI",
                   "ALUMINI", "LEADMINI",
                   "GOLDTEN", "GOLDGUINEA", "GOLDPETAL", "STEELREBAR", "KAPAS",
                   "NICKEL", "NATURALGAS", "LEAD", "GOLDM", "SILVERM",
                   "ALUMINIUM", "ZINC", "CRUDEOIL", "COPPER", "SILVER", "GOLD"]

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
                   master: dict | None = None, lots: int = 1) -> list[dict]:
    """Every tradeable calendar pair for one commodity, scored. See scan()."""
    from fyers_fetcher import get_depth
    from silvermic_spread import quote_many
    contracts = list_futures(commodity, min_dte=min_dte, master=master)
    if len(contracts) < 2:
        return []

    syms = [c["symbol"] for c in contracts]
    quotes = quote_many(syms, token)
    depth = get_depth(syms, token)          # ladder, so `lots` can be priced honestly
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

            # ── Real cost for the size you intend to trade ──────────────────
            # Preferred: walk both ladders for `lots` and add exact Zerodha charges
            # (verified against a live contract note). Falls back to the touch when
            # depth is unavailable, which UNDERSTATES cost — flagged as such.
            mult_c = _zm.multiplier(commodity) or 1.0
            nd, fd = depth.get(near["symbol"]), depth.get(far["symbol"])
            cost = fillable = None
            depth_used = False
            if nd and fd:
                ec = _mcc.execution_cost(nd, fd, lots, mult_c)
                fillable = ec.get("fillable_lots")
                if ec.get("fillable"):
                    cost = ec["total_per_unit"]
                    depth_used = True
            if cost is None:
                widths = [q.get("ask", 0) - q.get("bid", 0) for q in (nq, fq)]
                if all(w > 0 for w in widths):
                    charges = _mcc.spread_round_trip_charges(n_px * mult_c, f_px * mult_c)
                    cost = sum(widths) + charges / mult_c
            ratio = None if not cost else edge / cost

            if pos <= 25:
                bias, idea = "CHEAP", "LONG spread (buy far · sell near)"
            elif pos >= 75:
                bias, idea = "RICH", "SHORT spread (sell far · buy near)"
            else:
                bias, idea = "FAIR", "wait"
            units = mult_c
            margin_lot = _zm.margin_per_lot(commodity)
            # Both legs are held, so worst-case capital = 2 lots. MCX/Zerodha grant a
            # calendar-spread benefit that cuts this a lot — confirm in a Kite basket.
            margin_spread = None if margin_lot is None else margin_lot * 2
            edge_inr = None if units is None else edge * units
            roi = (None if (edge_inr is None or not margin_spread)
                   else edge_inr / margin_spread * 100)
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
                "lots":          lots,
                "depth_used":    depth_used,
                "fillable_lots": fillable,
                "idea":      idea if bias != "FAIR" else "—",
                "units":         units,
                "edge_inr":      None if edge_inr is None else round(edge_inr, 0),
                "cost_inr":      None if (units is None or cost is None) else round(cost * units, 0),
                "margin_spread": None if margin_spread is None else round(margin_spread),
                "roi_pct":       None if roi is None else round(roi, 2),
            })
    return rows


def affordable(budget: float = MARGIN_BUDGET_DEFAULT,
               commodities: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Split commodities into (within budget, too expensive) by single-leg NRML margin.
    A spread holds TWO legs, so real capital is up to 2x this (less with MCX's
    calendar-spread benefit)."""
    keep, drop = [], []
    for c in (commodities or ALL_COMMODITIES):
        m = _zm.margin_per_lot(c)
        (keep if (m is not None and m <= budget) else drop).append(c)
    return keep, drop


def scan(token: str, commodities: list[str] | None = None, lookback_days: int = 30,
         min_dte: int = 11, charge_rate: float = CHARGE_RATE_PCT,
         max_margin: float | None = MARGIN_BUDGET_DEFAULT, lots: int = 1,
         progress=None) -> list[dict]:
    """Scan several commodities and return every pair, best opportunity first
    (tradeable extremes with a payable edge rank above everything else).
    `max_margin` drops anything whose single-leg margin exceeds the budget."""
    commodities = commodities or LIQUID_DEFAULT
    if max_margin:
        commodities, _skipped = affordable(max_margin, commodities)
        if _skipped:
            logger.info("skipped (margin > %.0f): %s", max_margin, ", ".join(_skipped))
    if not commodities:
        return []
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
                                       master=master, lots=lots))
        except Exception as e:
            logger.warning("scan failed for %s: %s", c, e)
    rank = {"GOOD": 0, "THIN": 1, "NO_EDGE": 2, "UNKNOWN": 3}
    rows.sort(key=lambda r: (0 if r["bias"] in ("CHEAP", "RICH") else 1,
                             rank.get(r["verdict"], 9),
                             -(r["roi_pct"] or 0), -(r["ratio"] or 0)))
    return rows


def opportunities(rows: list[dict], min_ratio: float = 3.0) -> list[dict]:
    """Actionable subset: at a band extreme, the edge pays its own friction, AND the
    book can actually fill the intended size — an edge nobody will trade is not an
    opportunity."""
    return [r for r in rows
            if r["bias"] in ("CHEAP", "RICH") and (r["ratio"] or 0) >= min_ratio
            and (not r.get("depth_used") or (r.get("fillable_lots") or 0) >= r.get("lots", 1))]


def alert_text(r: dict) -> str:
    inr = (f" (₹{r['edge_inr']:,.0f} edge / ₹{r['cost_inr']:,.0f} cost per lot"
           + (f", {r['roi_pct']}% on ₹{r['margin_spread']:,.0f} margin)"
              if r.get("roi_pct") is not None else ")")
           if r.get("edge_inr") is not None else " per price unit")
    return (f"🔎 SPREAD OPPORTUNITY — {r['commodity']} {r['pair']}: {r['spread']:,.2f} "
            f"at {r['pos']}% of its {r['band_days']:.0f}d band ({r['bias']}) · "
            f"edge {r['ratio']}× cost{inr} → {r['idea']}")
