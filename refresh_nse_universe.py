#!/usr/bin/env python3
"""
refresh_nse_universe.py — regenerate nse_universe.py from NSE's live equity list.

Fetches NSE EQUITY_L.csv (all listed equities), filters to the tradeable EQ series,
auto-generates keywords + a heuristic sector, and writes nse_universe.py. Run by a
monthly GitHub Actions cron so new IPOs/delistings flow into the stock universe
automatically. Falls back to free proxies if NSE blocks the direct request.

Exit 0 on success (file written), 1 if the list could not be fetched (so the
workflow keeps the existing file instead of wiping it).
"""
from __future__ import annotations

import csv
import io
import re
import sys
import urllib.parse

import requests

_SOURCES = [
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
]
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

SECTOR_HINTS = [
    (["bank "], "Banking"),
    (["life insurance", "general insurance", "insurance", "assurance"], "Insurance"),
    (["asset management", "mutual fund"], "AMC/Wealth"),
    (["finance", "financial", "fincorp", "fintech", "capital ", "housing fin",
      "leasing", "securities", "broking"], "NBFC"),
    (["pharma", "pharmaceutical", "laborator", "lifescience", "life science",
      "biotech", "healthcare", "hospital", "drugs", "remedies", "diagnostic"], "Pharma"),
    (["software", "technologi", "technolog", "infotech", "systems", "digital",
      "cyber", "computer", "it solutions", "e-commerce"], "IT"),
    (["steel", "metal", "iron", "alloy", "aluminium", "copper", "zinc", "mining",
      "minerals", "ispat", "ferro"], "Metals"),
    (["power", "energy", "electric", "renewable", "solar", "hydro", "thermal",
      "green energy"], "Power"),
    (["cement", "concrete"], "Cement"),
    (["motor", "automobile", "auto ", "vehicle", "tyre", "forging", "bearing"], "Automobile"),
    (["chemical", "fertiliser", "fertilizer", "petrochem", "polymer", "dyes", "paints"], "Chemicals"),
    (["textile", "cotton", "garment", "apparel", "fabric", "spinning", "yarn"], "Textiles"),
    (["infra", "construction", "engineering", "projects", "builders"], "Infrastructure"),
    (["realty", "estates", "developers", "housing", "properties", "township"], "Real Estate"),
    (["petroleum", "oil", "gas ", "refiner", "lng"], "Oil & Gas"),
    (["food", "beverage", "sugar", "dairy", "agro", "breweries", "distiller", "tea", "coffee"], "FMCG"),
    (["telecom", "communication", "network", "broadband"], "Telecom"),
    (["hotel", "resort", "tourism", "leisure", "hospitality"], "Consumer"),
    (["media", "entertainment", "broadcast", "films", "television"], "Media"),
]


def _guess_sector(name: str) -> str:
    n = " " + name.lower() + " "
    for pats, sec in SECTOR_HINTS:
        if any(p in n for p in pats):
            return sec
    return "Other"


def _clean_name(name: str) -> str:
    n = re.sub(r"\((?:india|i)\)", " ", name, flags=re.I)
    n = re.sub(r"\b(?:ltd|limited|corporation|corp|co|company)\b\.?", " ", n, flags=re.I)
    n = re.sub(r"[.,]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _keywords(name: str, symbol: str) -> list[str]:
    kws = {symbol.lower()}
    cn = _clean_name(name).lower()
    if len(cn) >= 5 and cn != symbol.lower():
        kws.add(cn)
    return sorted(kws)


def _fetch_csv() -> str | None:
    headers = {"User-Agent": _UA, "Accept": "text/csv,*/*",
               "Referer": "https://www.nseindia.com/"}
    for url in _SOURCES:
        try:
            s = requests.Session(); s.headers.update(headers)
            try: s.get("https://www.nseindia.com/", timeout=10)
            except Exception: pass
            r = s.get(url, timeout=25)
            if r.status_code == 200 and "SYMBOL" in r.text[:200].upper():
                return r.text
        except Exception:
            pass
    # free-proxy fallback (NSE often blocks datacenter IPs)
    enc = urllib.parse.quote(_SOURCES[0], safe="")
    for p in (f"https://api.allorigins.win/raw?url={enc}",
              f"https://corsproxy.io/?url={enc}",
              f"https://thingproxy.freeboard.io/fetch/{_SOURCES[0]}"):
        try:
            r = requests.get(p, timeout=30, headers={"User-Agent": _UA})
            if r.status_code == 200 and "SYMBOL" in r.text[:300].upper():
                return r.text
        except Exception:
            continue
    return None


def main() -> int:
    text = _fetch_csv()
    if not text:
        print("ERROR: could not fetch EQUITY_L.csv (NSE blocked all routes) — keeping existing file")
        return 1

    rows = list(csv.DictReader(io.StringIO(text)))
    entries: dict[str, dict] = {}
    for r in rows:
        sym = (r.get("SYMBOL") or "").strip()
        series = (r.get(" SERIES") or r.get("SERIES") or "").strip()
        name = (r.get("NAME OF COMPANY") or "").strip()
        if series != "EQ" or len(sym) < 3:
            continue
        entries[sym] = {"name": _clean_name(name), "sector": _guess_sector(name),
                        "keywords": _keywords(name, sym)}

    if len(entries) < 1000:
        print(f"ERROR: only parsed {len(entries)} stocks — suspicious, keeping existing file")
        return 1

    with open("nse_universe.py", "w") as f:
        f.write('# ─────────────────────────────────────────────────────────────\n')
        f.write('# nse_universe.py — FULL NSE listed equity universe (SERIES=EQ).\n')
        f.write('# Source: NSE EQUITY_L.csv. Merged into config.STOCK_UNIVERSE LAST, so\n')
        f.write('# curated + Nifty500 entries (better names/sectors/keywords) take precedence.\n')
        f.write('# Sectors are heuristic from the company name ("Other" when unknown).\n')
        f.write('# AUTO-GENERATED by refresh_nse_universe.py — do not edit by hand.\n')
        f.write('# ─────────────────────────────────────────────────────────────\n')
        f.write("NSE_UNIVERSE = {\n")
        for sym in sorted(entries):
            e = entries[sym]
            f.write(f"    {sym!r}: {{\"name\": {e['name']!r}, \"sector\": {e['sector']!r}, "
                    f"\"keywords\": {e['keywords']!r}}},\n")
        f.write("}\n")
    print(f"OK: wrote nse_universe.py with {len(entries)} EQ stocks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
