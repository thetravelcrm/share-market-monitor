# ─────────────────────────────────────────────────────────────
#  silver_news_intel.py  –  Silver-specific News Intelligence Engine
#
#  Acts as the FINAL decision gate for SILVERMIC trades:
#    Technical GREEN + News Bullish  → CONFIRMED (take trade)
#    Technical GREEN + News Neutral  → WAIT (no trade)
#    Technical GREEN + News Bearish  → AVOID (trap signal)
#
#  Reuses the existing news pipeline (news_fetcher + sentiment_analyzer)
#  and adds silver-specific scoring: inverse relationships, recency
#  weighting, source credibility, and macro impact classification.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import math
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from news_fetcher import NewsItem, fetch_all_feeds
from sentiment_analyzer import analyze as vader_analyze

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
#  Silver-relevant keyword filter
# ─────────────────────────────────────────────────────────────
_SILVER_KEYWORDS: list[str] = [
    # Direct silver
    "silver", "silvermic", "precious metal", "bullion", "comex", "lbma",
    "safe haven", "industrial metal", "photovoltaic", "solar panel",
    "gold silver ratio", "silver demand", "silver supply", "silver etf",
    # Macro triggers that move silver
    "fed rate", "federal reserve", "interest rate", "rate cut", "rate hike",
    "inflation", "cpi", "pce", "core inflation",
    "dollar index", "dxy", "us dollar", "usd",
    "treasury yield", "bond yield", "real yield",
    "geopolit", "war", "crisis", "sanction", "tariff", "trade war",
    "china manufacturing", "china pmi", "industrial output",
    "gold", "copper", "base metal",
]

# Pre-compiled patterns for speed
_SILVER_PATTERNS = [
    re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE)
    for kw in _SILVER_KEYWORDS
]


def _is_silver_relevant(item: NewsItem) -> bool:
    """Check if a news article is relevant to silver price movement."""
    text = item.raw_text
    return any(p.search(text) for p in _SILVER_PATTERNS)


# ─────────────────────────────────────────────────────────────
#  Inverse relationship rules
#
#  Silver doesn't always move in the same direction as the news
#  sentiment.  A "positive" article about dollar strength is
#  BEARISH for silver.  These rules detect such relationships
#  and flip the score direction accordingly.
# ─────────────────────────────────────────────────────────────
_INVERSE_RULES: list[tuple[list[str], float]] = [
    # USD strength → Silver bearish
    (["dollar strength", "dollar rally", "dxy rise", "dxy surge",
      "usd surge", "usd rally", "dollar soar", "greenback strength",
      "dollar gain", "strong dollar"], -1.0),
    # USD weakness → Silver bullish
    (["dollar weak", "dollar fall", "dxy drop", "dxy decline",
      "usd decline", "usd fall", "dollar slump", "greenback weak",
      "dollar slide", "weak dollar"], +1.0),
    # Rate cut / dovish → Silver bullish
    (["rate cut", "dovish", "pause rate", "rate hold", "rate unchanged",
      "easing cycle", "monetary easing", "lower rate"], +1.0),
    # Rate hike / hawkish → Silver bearish
    (["rate hike", "hawkish", "tightening", "rate increase",
      "higher rate", "monetary tightening"], -1.0),
    # Inflation rise → Silver bullish (inflation hedge)
    (["inflation rise", "cpi higher", "inflation surge", "inflation up",
      "rising inflation", "hot inflation", "inflation spike",
      "pce above", "core inflation rise"], +1.0),
    # Inflation cooling → Silver bearish (less need for hedge)
    (["inflation cool", "inflation ease", "cpi below", "inflation fall",
      "disinflation", "deflation", "inflation slow"], -1.0),
    # Geopolitical crisis → Silver bullish (safe haven)
    (["war", "military conflict", "geopolitical tension", "geopolitical crisis",
      "sanction", "trade war", "escalat", "missile", "invasion"], +1.0),
    # Peace / de-escalation → Silver bearish (risk-on)
    (["peace talk", "ceasefire", "de-escalat", "diplomatic resolution",
      "tension eas", "truce"], -1.0),
    # Industrial growth → Silver bullish (demand)
    (["manufacturing growth", "pmi rise", "pmi above", "china recovery",
      "industrial output rise", "factory output rise", "industrial boom",
      "manufacturing expand", "china rebound"], +1.0),
    # Industrial slowdown → Silver bearish (demand drop)
    (["industrial slowdown", "manufacturing contract", "pmi decline",
      "pmi below", "china slowdown", "factory output fall",
      "manufacturing shrink", "recession fear"], -1.0),
]

# Pre-compile inverse patterns
_INVERSE_COMPILED: list[tuple[list[re.Pattern], float]] = [
    ([re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE) for kw in kws], direction)
    for kws, direction in _INVERSE_RULES
]


def _apply_inverse_relationships(text: str, base_score: float) -> float:
    """
    Adjust VADER score to reflect silver's actual price direction.

    Example: "Dollar rallies to 6-month high" → VADER says +0.4 (positive article).
    But dollar strength is BEARISH for silver, so we return -0.4.
    """
    for patterns, silver_direction in _INVERSE_COMPILED:
        if any(p.search(text) for p in patterns):
            # Keyword matched.  Use the magnitude of VADER score but apply
            # the silver-specific direction.
            magnitude = abs(base_score) if abs(base_score) > 0.05 else 0.3
            return magnitude * silver_direction

    # No inverse rule matched — use VADER score as-is
    # (direct silver news: "silver rallies" → positive → bullish)
    return base_score


# ─────────────────────────────────────────────────────────────
#  Weighting functions
# ─────────────────────────────────────────────────────────────
def _recency_weight(published: datetime) -> float:
    """Exponential decay: recent news matters more.
    0h → 1.0, 3h → 0.64, 6h → 0.41, 12h → 0.17, 24h → 0.03"""
    now = datetime.now(timezone.utc)
    hours_old = max(0, (now - published).total_seconds() / 3600)
    return max(0.1, math.exp(-0.15 * hours_old))


# Source credibility tiers
_HIGH_CRED = ["reuters", "bloomberg", "financial times", "cnbc", "rbi",
              "federal reserve", "fed", "wall street journal", "ft"]
_MED_CRED  = ["economic times", "moneycontrol", "mint", "business standard",
              "investing.com", "mining.com", "livemint", "financial express",
              "hindu business line", "kitco", "tradingview"]
_LOW_CRED  = ["zee business", "ndtv", "yahoo"]


def _source_credibility(source: str) -> float:
    """Score 0.4–1.0 based on source reliability."""
    src = source.lower()
    if any(h in src for h in _HIGH_CRED):
        return 1.0
    if any(m in src for m in _MED_CRED):
        return 0.75
    if any(lo in src for lo in _LOW_CRED):
        return 0.5
    return 0.4


# Impact classification patterns
_IMPACT_TIERS: list[tuple[list[str], float]] = [
    # Central bank decisions — highest impact
    (["fed rate", "federal reserve", "fomc", "rbi policy", "ecb rate",
      "boj rate", "central bank", "rate decision", "monetary policy"], 1.0),
    # Inflation / key economic data
    (["cpi", "pce", "inflation data", "gdp", "jobs report", "nonfarm",
      "unemployment", "pmi", "industrial production"], 0.9),
    # Geopolitical events
    (["war", "military", "sanction", "geopolit", "crisis", "invasion",
      "missile", "nuclear", "trade war", "tariff"], 0.85),
    # Industrial demand / supply data
    (["silver demand", "silver supply", "photovoltaic", "solar",
      "industrial output", "china factory", "manufacturing data"], 0.7),
    # General commodity / market commentary
    (["commodity", "precious metal", "bullion", "gold silver",
      "safe haven", "comex", "lbma", "silver price"], 0.5),
]

_IMPACT_COMPILED: list[tuple[list[re.Pattern], float]] = [
    ([re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE) for kw in kws], weight)
    for kws, weight in _IMPACT_TIERS
]


def _impact_weight(text: str) -> float:
    """Return impact weight 0.3–1.0 based on news category."""
    for patterns, weight in _IMPACT_COMPILED:
        if any(p.search(text) for p in patterns):
            return weight
    return 0.3  # Blog / generic opinion


# ─────────────────────────────────────────────────────────────
#  Article scoring
# ─────────────────────────────────────────────────────────────
def _score_article(item: NewsItem) -> dict:
    """Score a single article for silver price direction."""
    sentiment = vader_analyze(item)
    base_score = sentiment.score  # -1 to +1

    silver_dir = _apply_inverse_relationships(item.raw_text, base_score)
    recency    = _recency_weight(item.published)
    source_w   = _source_credibility(item.source)
    impact_w   = _impact_weight(item.raw_text)

    final = silver_dir * recency * impact_w * source_w

    # Build one-line insight
    direction = "bullish" if silver_dir > 0 else ("bearish" if silver_dir < 0 else "neutral")
    insight = f"{item.title[:80]} → {direction} for silver"

    return {
        "base_score":       base_score,
        "silver_direction": silver_dir,
        "recency_weight":   round(recency, 3),
        "impact_weight":    impact_w,
        "source_weight":    source_w,
        "final_weighted":   round(final, 4),
        "insight":          insight,
        "title":            item.title,
        "source":           item.source,
        "published":        item.published,
    }


# ─────────────────────────────────────────────────────────────
#  Verdict dataclass
# ─────────────────────────────────────────────────────────────
@dataclass
class SilverNewsVerdict:
    score: float                              # 0–10 compound
    label: str                                # "Strong Bullish" / "Bullish" / "Neutral" / "Bearish" / "Strong Bearish" / "No Data"
    decision: str                             # "CONFIRMED" / "WAIT" / "AVOID"
    confidence: float                         # 0–10
    top_insights: list[str] = field(default_factory=list)
    risk_flags: list[str]   = field(default_factory=list)
    article_count: int      = 0
    fetched_at: datetime    = field(default_factory=lambda: datetime.now(timezone.utc))


def _classify_verdict(score: float) -> tuple[str, str]:
    """Map 0–10 score to (label, decision)."""
    if score >= 7.5:
        return "Strong Bullish", "CONFIRMED"
    if score >= 6.0:
        return "Bullish", "CONFIRMED"
    if score >= 4.5:
        return "Neutral", "WAIT"
    if score >= 3.0:
        return "Bearish", "AVOID"
    return "Strong Bearish", "AVOID"


# ─────────────────────────────────────────────────────────────
#  Main entry point
# ─────────────────────────────────────────────────────────────
def get_silver_verdict(hours_back: int = 12) -> SilverNewsVerdict:
    """
    Fetch news, filter to silver-relevant, score each article,
    and return a compound verdict for use as the SILVERMIC trade gate.
    """
    try:
        all_news = fetch_all_feeds(hours_back=hours_back)
    except Exception as e:
        logger.warning("News fetch failed: %s", e)
        return SilverNewsVerdict(
            score=5.0, label="No Data", decision="WAIT",
            confidence=0.0,
            risk_flags=[f"News fetch failed: {e}"],
        )

    silver_news = [item for item in all_news if _is_silver_relevant(item)]

    if not silver_news:
        return SilverNewsVerdict(
            score=5.0, label="No Data", decision="WAIT",
            confidence=1.0, article_count=0,
            risk_flags=[f"No silver-relevant news in last {hours_back}h"],
        )

    # Score each article
    scored = [_score_article(item) for item in silver_news]

    # Weighted compound score: sum(final_weighted) / sum(abs_weights)
    total_weighted = sum(s["final_weighted"] for s in scored)
    total_abs_weight = sum(
        abs(s["silver_direction"]) * s["recency_weight"] * s["impact_weight"] * s["source_weight"]
        for s in scored
    )

    if total_abs_weight > 0:
        # Normalize to -1..+1 range
        raw = total_weighted / total_abs_weight
    else:
        raw = 0.0

    # Map -1..+1 → 0..10 (5.0 = neutral)
    compound_score = round(max(0.0, min(10.0, 5.0 + raw * 5.0)), 1)

    label, decision = _classify_verdict(compound_score)

    # Confidence: based on article count + consistency
    directions = [s["silver_direction"] for s in scored]
    bullish_count = sum(1 for d in directions if d > 0.05)
    bearish_count = sum(1 for d in directions if d < -0.05)
    total_dir = bullish_count + bearish_count
    consistency = max(bullish_count, bearish_count) / total_dir if total_dir > 0 else 0.5

    # More articles + higher consistency = higher confidence
    count_factor = min(1.0, len(silver_news) / 5.0)  # saturates at 5 articles
    confidence = round(min(10.0, (consistency * 6 + count_factor * 4)), 1)

    # Top insights — pick top 3 by absolute weighted score
    sorted_scored = sorted(scored, key=lambda s: abs(s["final_weighted"]), reverse=True)
    top_insights = [s["insight"] for s in sorted_scored[:3]]

    # Risk flags
    risk_flags: list[str] = []

    if bullish_count > 0 and bearish_count > 0:
        ratio = min(bullish_count, bearish_count) / max(bullish_count, bearish_count)
        if ratio > 0.4:
            risk_flags.append("Conflicting news — mixed signals, proceed with caution")

    avg_age_hours = sum(
        (datetime.now(timezone.utc) - s["published"]).total_seconds() / 3600
        for s in scored
    ) / len(scored)
    if avg_age_hours > 12:
        risk_flags.append("Stale news — most articles >12h old, check for recent developments")

    # High volatility detection
    high_impact_count = sum(1 for s in scored if s["impact_weight"] >= 0.85)
    if high_impact_count >= 2:
        risk_flags.append("Multiple high-impact events — expect elevated volatility")

    return SilverNewsVerdict(
        score=compound_score,
        label=label,
        decision=decision,
        confidence=confidence,
        top_insights=top_insights,
        risk_flags=risk_flags,
        article_count=len(silver_news),
    )
