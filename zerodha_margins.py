# ─────────────────────────────────────────────────────────────
#  zerodha_margins.py — MCX contract multipliers + NRML margins.
#
#  Source: Zerodha's own commodity margin calculator
#  (https://zerodha.com/margin-calculator/Commodity/), which publishes, per contract:
#  lot size, NRML margin ₹/lot, margin rate %, and the reference price.
#
#  The PRICE MULTIPLIER (₹ P&L per 1.00 of price move, per lot) is not printed
#  directly, but it is recoverable exactly, because margin = rate × contract value:
#
#        multiplier = margin ÷ (rate × price)
#
#  That derivation is self-consistent (it rounds cleanly to 2500 for COPPER, 100 for
#  CRUDEOIL, 1 for SILVERMIC …) and it automatically handles quotation quirks — GOLDM
#  is a 100 g lot quoted per 10 g, so its multiplier is 10, not 100. Guessing from
#  "lot size" alone gets that wrong by 10×.
#
#  Live values are fetched and cached daily; FALLBACK keeps the app correct offline.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import html
import logging
import re
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_URL = "https://zerodha.com/margin-calculator/Commodity/"

# Snapshot taken 05 Aug 2026. Multipliers are contract specs (stable); the margin
# figures drift daily, so treat them as indicative until a live fetch succeeds.
FALLBACK: dict[str, dict] = {
    "ALUMINI":    {"lot": "1 MT",       "mult": 1000, "margin": 32312,   "rate": 9.37},
    "ALUMINIUM":  {"lot": "5 MT",       "mult": 5000, "margin": 161550,  "rate": 9.37},
    "COPPER":     {"lot": "2500 KGS",   "mult": 2500, "margin": 315156,  "rate": 9.24},
    "COTTON":     {"lot": "25 BALES",   "mult": 25,   "margin": 73306,   "rate": 9.25},
    "CRUDEOIL":   {"lot": "100 BBL",    "mult": 100,  "margin": 225417,  "rate": 31.25},
    "CRUDEOILM":  {"lot": "10 BBL",     "mult": 10,   "margin": 22552,   "rate": 31.25},
    "GOLD":       {"lot": "1 KGS",      "mult": 100,  "margin": 1318936, "rate": 9.25},
    "GOLDGUINEA": {"lot": "8 GRMS",     "mult": 1,    "margin": 10671,   "rate": 9.25},
    "GOLDM":      {"lot": "100 GRMS",   "mult": 10,   "margin": 132021,  "rate": 9.25},
    "GOLDPETAL":  {"lot": "1 GRMS",     "mult": 1,    "margin": 1334,    "rate": 9.25},
    "GOLDTEN":    {"lot": "10 GRMS",    "mult": 1,    "margin": 13285,   "rate": 9.25},
    "LEAD":       {"lot": "5 MT",       "mult": 5000, "margin": 72443,   "rate": 7.28},
    "LEADMINI":   {"lot": "1 MT",       "mult": 1000, "margin": 14489,   "rate": 7.28},
    "MENTHAOIL":  {"lot": "360 KGS",    "mult": 360,  "margin": 70035,   "rate": 15.65},
    "NATGASMINI": {"lot": "250 MMBTU",  "mult": 250,  "margin": 9549,    "rate": 14.93},
    "NATURALGAS": {"lot": "1250 MMBTU", "mult": 1250, "margin": 47748,   "rate": 14.93},
    "NICKEL":     {"lot": "250 KGS",    "mult": 250,  "margin": 46403,   "rate": 11.26},
    "SILVER":     {"lot": "30 KGS",     "mult": 30,   "margin": 940475,  "rate": 14.15},
    "SILVER100":  {"lot": "100 GRMS",   "mult": 10,   "margin": 2893,    "rate": 12.96},
    "SILVERM":    {"lot": "5 KGS",      "mult": 5,    "margin": 149147,  "rate": 13.33},
    "SILVERMIC":  {"lot": "1 KGS",      "mult": 1,    "margin": 29755,   "rate": 13.30},
    "ZINC":       {"lot": "5 MT",       "mult": 5000, "margin": 179215,  "rate": 9.25},
    "ZINCMINI":   {"lot": "1 MT",       "mult": 1000, "margin": 35843,   "rate": 9.25},
}

_cache: dict = {"day": None, "data": None}

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.S)
_NAME_RE = re.compile(r"([A-Z][A-Z0-9]*)\s+\w+\s+\d{4}\s+Lot size\s+([\d.]+)\s+(\S+)")


def _round_mult(x: float) -> int:
    """Snap a derived multiplier to its clean contract value (2498.7 -> 2500)."""
    for step in (1000, 500, 100, 50, 10, 5, 1):
        if x >= step and abs(x - round(x / step) * step) <= max(3.0, x * 0.003):
            return int(round(x / step) * step)
    return int(round(x))


def load(force: bool = False) -> dict[str, dict]:
    """{COMMODITY: {lot, mult, margin, rate}} — live when reachable, else FALLBACK.
    The HIGHEST margin across a commodity's listed months is kept: a calendar spread
    holds two different expiries, and a far month can carry a bigger margin than the
    near one (ALUMINI Aug 32,312 vs Oct 35,321), so budgeting on the cheapest row
    would understate what the trade actually costs."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not force and _cache["day"] == today and _cache["data"]:
        return _cache["data"]
    try:
        req = urllib.request.Request(_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            page = r.read().decode("utf-8", "ignore")
        out: dict[str, dict] = {}
        for row in _ROW_RE.findall(page):
            cells = [re.sub(r"\s+", " ", html.unescape(re.sub("<.*?>", " ", c))).strip()
                     for c in _CELL_RE.findall(row)]
            cells = [c for c in cells if c]
            if len(cells) < 4:
                continue
            m = _NAME_RE.match(cells[0])
            if not m:
                continue
            try:
                margin = float(cells[1].replace(",", ""))
                rate = float(cells[2].rstrip("%")) / 100
                price = float(cells[3].replace(",", ""))
            except Exception:
                continue
            if not (margin and rate and price):
                continue
            prev = out.get(m.group(1))
            if prev and prev["margin"] >= margin:
                continue                      # keep the most expensive month
            out[m.group(1)] = {
                "lot":    f"{float(m.group(2)):g} {m.group(3)}",
                "mult":   _round_mult(margin / (rate * price)),
                "margin": round(margin),
                "rate":   round(rate * 100, 2),
            }
        if len(out) >= 10:
            _cache.update({"day": today, "data": out})
            logger.info("Zerodha margins loaded for %d commodities", len(out))
            return out
        logger.warning("margin page parsed only %d rows — using fallback", len(out))
    except Exception as e:
        logger.warning("margin fetch failed (%s) — using fallback", e)
    _cache.update({"day": today, "data": FALLBACK})
    return FALLBACK


def info(commodity: str) -> dict | None:
    return load().get(commodity) or FALLBACK.get(commodity)


def multiplier(commodity: str) -> float | None:
    """₹ P&L per 1.00 of price move, per lot."""
    d = info(commodity)
    return float(d["mult"]) if d else None


def margin_per_lot(commodity: str) -> float | None:
    d = info(commodity)
    return float(d["margin"]) if d else None
