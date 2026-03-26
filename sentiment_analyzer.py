# ─────────────────────────────────────────────────────────────
#  sentiment_analyzer.py  –  NLP sentiment + category tagging
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import re
from dataclasses import dataclass
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from config import CATEGORY_KEYWORDS, MACRO_SECTOR_MAP
from news_fetcher import NewsItem

_analyzer = SentimentIntensityAnalyzer()

# Finance-specific lexicon adjustments
_FINANCE_LEXICON = {
    # Positive signals
    "beat":         2.5,  "beats":        2.5,  "outperform":   2.0,
    "upgrade":      2.0,  "upgraded":     2.0,  "rally":        2.0,
    "surge":        2.0,  "surged":       2.0,  "breakout":     1.8,
    "buyback":      1.5,  "dividend":     1.5,  "acquisition":  1.0,
    "record":       1.5,  "strong":       1.5,  "robust":       1.5,
    "recovery":     1.5,  "bullish":      2.5,  "growth":       1.2,
    "approval":     1.8,  "approved":     1.8,  "contract":     1.5,
    "deal":         1.2,  "partnership":  1.2,  "profit":       1.5,
    # Negative signals
    "miss":        -2.5,  "misses":      -2.5,  "downgrade":   -2.0,
    "downgraded":  -2.0,  "selloff":     -2.5,  "crash":       -3.0,
    "collapse":    -3.0,  "default":     -3.0,  "bankruptcy":  -3.5,
    "fraud":       -3.5,  "scam":        -3.5,  "penalty":     -2.0,
    "fine":        -1.8,  "ban":         -2.0,  "loss":        -2.0,
    "bearish":     -2.5,  "recession":   -2.5,  "slowdown":    -1.5,
    "inflation":   -1.2,  "layoff":      -2.0,  "layoffs":     -2.0,
    "write-off":   -2.5,  "impairment":  -2.0,  "debt":        -1.0,
    "downside":    -1.5,  "concern":     -1.2,  "warning":     -1.5,
    "tariff":      -1.5,  "war":         -2.5,  "sanction":    -2.0,
}
_analyzer.lexicon.update(_FINANCE_LEXICON)


@dataclass
class SentimentResult:
    label: str          # "Positive" | "Negative" | "Neutral"
    score: float        # Compound score -1 → +1
    positive: float
    negative: float
    neutral: float
    category: str       # "Earnings" | "Macro" | etc.
    macro_sectors: list[str]   # sectors affected via macro keywords


def analyze(item: NewsItem) -> SentimentResult:
    text = item.raw_text
    scores = _analyzer.polarity_scores(text)
    compound = scores["compound"]

    if compound >= 0.05:
        label = "Positive"
    elif compound <= -0.05:
        label = "Negative"
    else:
        label = "Neutral"

    category = _detect_category(text)
    macro_sectors = _detect_macro_sectors(text)

    return SentimentResult(
        label=label,
        score=round(compound, 4),
        positive=scores["pos"],
        negative=scores["neg"],
        neutral=scores["neu"],
        category=category,
        macro_sectors=macro_sectors,
    )


def _detect_category(text: str) -> str:
    scores: dict[str, int] = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits:
            scores[cat] = hits
    if not scores:
        return "General"
    return max(scores, key=scores.__getitem__)


def _detect_macro_sectors(text: str) -> list[str]:
    affected: set[str] = set()
    for kw, sectors in MACRO_SECTOR_MAP.items():
        if kw in text:
            affected.update(sectors)
    return list(affected)


def sentiment_bar(score: float, width: int = 20) -> str:
    """Return a visual ASCII sentiment bar."""
    norm = (score + 1) / 2           # map -1..1  →  0..1
    filled = round(norm * width)
    bar = "█" * filled + "░" * (width - filled)
    if score >= 0.05:
        color = "green"
    elif score <= -0.05:
        color = "red"
    else:
        color = "yellow"
    return bar, color
