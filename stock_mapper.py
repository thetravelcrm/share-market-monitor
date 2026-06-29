# ─────────────────────────────────────────────────────────────
#  stock_mapper.py  –  Map news → affected stocks + sectors
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import re
from dataclasses import dataclass

from config import STOCK_UNIVERSE, SECTOR_STOCKS
from news_fetcher import NewsItem
from sentiment_analyzer import SentimentResult


def _kw_match(keyword: str, text: str) -> bool:
    """Case-insensitive whole-word match (word boundaries).
    Prevents 'tata' matching inside 'data', or 'ai' matching inside 'rain'."""
    return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text, re.IGNORECASE))


@dataclass
class StockMatch:
    symbol: str
    name: str
    sector: str
    relation: str        # "Direct" | "Sectoral" | "Macro"
    match_reason: str    # keyword or sector that triggered match


# The cascade was designed for the curated universe (sectors of ~10-26 stocks).
# With the full NSE universe, sectors are huge (e.g. "Other" ~900), so an
# uncapped cascade maps one headline to 100+ symbols and the price prefetch
# grinds for minutes. Cap peers per sector (the list is curated-first, so the
# cap keeps the most liquid names) and never cascade the unclassified bucket.
_MAX_SECTOR_CASCADE = 12
_NO_CASCADE_SECTORS = {"Other"}


def map_stocks(item: NewsItem, sentiment: SentimentResult) -> list[StockMatch]:
    """
    Return a deduplicated list of stocks affected by a news item,
    combining direct keyword matches, sector cascade, and macro impact.
    """
    matched: dict[str, StockMatch] = {}

    # ── 1. Direct keyword match (whole-word, case-insensitive) ──
    # A real catalyst names the stock in the HEADLINE. A keyword found only in the
    # body/summary is usually a peer or passing mention (e.g. a defence article about
    # Apollo Micro that lists "Bharat Electronics" among peers) — tag those as a weak
    # "Mention" so they can't fire an EXTREME Direct signal.
    _title = item.title or ""
    for symbol, meta in STOCK_UNIVERSE.items():
        for kw in meta["keywords"]:
            if _kw_match(kw, item.raw_text):
                rel = "Direct" if _kw_match(kw, _title) else "Mention"
                if symbol not in matched:
                    matched[symbol] = StockMatch(
                        symbol=symbol,
                        name=meta["name"],
                        sector=meta["sector"],
                        relation=rel,
                        match_reason=f'keyword: "{kw}"' + ("" if rel == "Direct" else " (body mention)"),
                    )
                break

    # ── 2. Sector cascade from macro keywords ─────────────────
    for sector in sentiment.macro_sectors:
        if sector in _NO_CASCADE_SECTORS:
            continue
        for symbol in SECTOR_STOCKS.get(sector, [])[:_MAX_SECTOR_CASCADE]:
            if symbol not in matched:
                matched[symbol] = StockMatch(
                    symbol=symbol,
                    name=STOCK_UNIVERSE[symbol]["name"],
                    sector=STOCK_UNIVERSE[symbol]["sector"],
                    relation="Macro",
                    match_reason=f"macro sector: {sector}",
                )

    # ── 3. Sector siblings of direct matches (indirect impact) ─
    direct_sectors = {v.sector for v in matched.values() if v.relation == "Direct"}
    for sector in direct_sectors:
        if sector in _NO_CASCADE_SECTORS:
            continue
        for symbol in SECTOR_STOCKS.get(sector, [])[:_MAX_SECTOR_CASCADE]:
            if symbol not in matched:
                matched[symbol] = StockMatch(
                    symbol=symbol,
                    name=STOCK_UNIVERSE[symbol]["name"],
                    sector=STOCK_UNIVERSE[symbol]["sector"],
                    relation="Sectoral",
                    match_reason=f"sector peer: {sector}",
                )

    # Sort: Direct first, then Sectoral, then Macro, then weak body Mentions
    order = {"Direct": 0, "Sectoral": 1, "Macro": 2, "Mention": 3}
    return sorted(matched.values(), key=lambda x: (order.get(x.relation, 4), x.symbol))
