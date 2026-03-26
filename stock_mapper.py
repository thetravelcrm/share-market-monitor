# ─────────────────────────────────────────────────────────────
#  stock_mapper.py  –  Map news → affected stocks + sectors
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

from dataclasses import dataclass, field

from config import STOCK_UNIVERSE, SECTOR_STOCKS
from news_fetcher import NewsItem
from sentiment_analyzer import SentimentResult


@dataclass
class StockMatch:
    symbol: str
    name: str
    sector: str
    relation: str        # "Direct" | "Sectoral" | "Macro"
    match_reason: str    # keyword or sector that triggered match


def map_stocks(item: NewsItem, sentiment: SentimentResult) -> list[StockMatch]:
    """
    Return a deduplicated list of stocks affected by a news item,
    combining direct keyword matches, sector cascade, and macro impact.
    """
    matched: dict[str, StockMatch] = {}

    # ── 1. Direct keyword match ───────────────────────────────
    for symbol, meta in STOCK_UNIVERSE.items():
        for kw in meta["keywords"]:
            if kw in item.raw_text:
                if symbol not in matched:
                    matched[symbol] = StockMatch(
                        symbol=symbol,
                        name=meta["name"],
                        sector=meta["sector"],
                        relation="Direct",
                        match_reason=f'keyword: "{kw}"',
                    )
                break

    # ── 2. Sector cascade from macro keywords ─────────────────
    for sector in sentiment.macro_sectors:
        for symbol in SECTOR_STOCKS.get(sector, []):
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
        for symbol in SECTOR_STOCKS.get(sector, []):
            if symbol not in matched:
                matched[symbol] = StockMatch(
                    symbol=symbol,
                    name=STOCK_UNIVERSE[symbol]["name"],
                    sector=STOCK_UNIVERSE[symbol]["sector"],
                    relation="Sectoral",
                    match_reason=f"sector peer: {sector}",
                )

    # Sort: Direct first, then Sectoral, then Macro
    order = {"Direct": 0, "Sectoral": 1, "Macro": 2}
    return sorted(matched.values(), key=lambda x: (order[x.relation], x.symbol))
