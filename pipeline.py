# ─────────────────────────────────────────────────────────────
#  pipeline.py  –  Shared data pipeline (used by CLI + Streamlit)
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from news_fetcher        import fetch_all_feeds, deduplicate, NewsItem
from sentiment_analyzer  import analyze as analyze_sentiment, SentimentResult
from stock_mapper        import map_stocks
from impact_analyzer     import analyze_impact, ImpactResult
from signal_engine       import generate_signal, TradeSignal

_IMPACT_ORDER = {"EXTREME": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}


@dataclass
class PipelineResult:
    run_time:        datetime
    items_total:     int
    items_analyzed:  int
    # (NewsItem, SentimentResult, [ImpactResult])  — sorted by impact strength
    news_impacts:    list[tuple[NewsItem, SentimentResult, list[ImpactResult]]] = field(default_factory=list)
    # (NewsItem, ImpactResult, TradeSignal)
    all_signals:     list[tuple[NewsItem, ImpactResult, TradeSignal]]           = field(default_factory=list)
    underreacted:    list[tuple[NewsItem, ImpactResult, TradeSignal]]           = field(default_factory=list)
    # (headline_snippet, ImpactResult)  – direct matches only, de-duped by symbol
    top5:            list[tuple[str, ImpactResult]]                             = field(default_factory=list)
    # all flat direct matches (for sector rotation)
    flat_impacts:    list[tuple[str, ImpactResult]]                             = field(default_factory=list)
    warnings:        list[str]                                                  = field(default_factory=list)
    # NSE market data
    fii_dii:             Optional[dict]  = None
    bulk_deals:          list[dict]      = field(default_factory=list)
    block_deals:         list[dict]      = field(default_factory=list)
    corporate_events:    list[dict]      = field(default_factory=list)
    nifty_data:          Optional[dict]  = None


def run_pipeline(
    hours:        int  = 12,
    top_n:        int  = 25,
    fetch_prices: bool = True,
    progress_cb   = None,   # optional callable(step: str, pct: float)
) -> PipelineResult:
    """
    Full analysis pipeline.  Returns a PipelineResult with all data
    needed to render either a CLI dashboard or a Streamlit UI.
    """
    result = PipelineResult(run_time=datetime.now(tz=timezone.utc), items_total=0, items_analyzed=0)

    # ── 0. NSE market data (non-blocking, all silent-fail) ────
    if progress_cb: progress_cb("Fetching NSE market data…", 0.02)
    try:
        from nse_data import fetch_fii_dii, fetch_bulk_deals, fetch_block_deals, \
                             fetch_corporate_events, fetch_gift_nifty
        result.fii_dii          = fetch_fii_dii()
        result.bulk_deals       = fetch_bulk_deals()
        result.block_deals      = fetch_block_deals()
        result.corporate_events = fetch_corporate_events(days_ahead=7)
        result.nifty_data       = fetch_gift_nifty()
    except Exception:
        pass

    # ── 1. Fetch & dedup ──────────────────────────────────────
    if progress_cb: progress_cb("Fetching news feeds…", 0.05)
    try:
        raw   = fetch_all_feeds(hours_back=hours, max_per_feed=30)
        items = deduplicate(raw)
    except Exception as exc:
        result.warnings.append(f"Feed fetch error: {exc}")
        return result

    result.items_total = len(items)
    if not items:
        result.warnings.append("No articles found — check connectivity or increase --hours.")
        return result

    # ── 2. NLP + Impact per item ──────────────────────────────
    total = min(len(items), top_n)
    all_impacts: list[tuple[NewsItem, SentimentResult, list[ImpactResult]]] = []

    for i, item in enumerate(items[:top_n]):
        if progress_cb:
            progress_cb(f"Analysing: {item.title[:60]}…", 0.1 + 0.8 * (i / total))

        sentiment = analyze_sentiment(item)
        if abs(sentiment.score) < 0.03 and not sentiment.macro_sectors:
            continue

        matches = map_stocks(item, sentiment)
        if not matches:
            continue

        impacts = analyze_impact(
            item, sentiment, matches,
            max_stocks=8,
            fetch_prices=fetch_prices,
        )

        all_impacts.append((item, sentiment, impacts))
        result.items_analyzed += 1

        for imp in impacts:
            sig = generate_signal(imp)
            if sig:
                result.all_signals.append((item, imp, sig))
                if imp.reaction_status == "Underreacted":
                    result.underreacted.append((item, imp, sig))

    # ── 3. Sort by max impact strength ───────────────────────
    all_impacts.sort(
        key=lambda x: max((_IMPACT_ORDER.get(r.impact_strength, 0) for r in x[2]), default=0),
        reverse=True,
    )
    result.news_impacts = all_impacts

    # ── 4. Build top5 + flat_impacts ─────────────────────────
    flat: list[tuple[str, ImpactResult]] = []
    for item, _, impacts in all_impacts:
        for r in impacts:
            if r.relation == "Direct":
                flat.append((item.title[:50], r))

    result.flat_impacts = flat

    seen: dict[str, tuple[str, ImpactResult]] = {}
    for headline, r in flat:
        if r.symbol not in seen or (
            _IMPACT_ORDER.get(r.impact_strength, 0) > _IMPACT_ORDER.get(seen[r.symbol][1].impact_strength, 0)
        ):
            seen[r.symbol] = (headline, r)

    result.top5 = sorted(
        seen.values(),
        key=lambda x: (_IMPACT_ORDER.get(x[1].impact_strength, 0), abs(x[1].actual_move_pct)),
        reverse=True,
    )[:5]

    # ── 5. Sort underreacted by confidence ───────────────────
    result.underreacted.sort(
        key=lambda x: (x[2].confidence, abs(x[1].expected_move_pct - x[1].actual_move_pct)),
        reverse=True,
    )

    if progress_cb: progress_cb("Done", 1.0)
    return result
