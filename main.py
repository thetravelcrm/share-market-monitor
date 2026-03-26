#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────
#  main.py  –  Orchestrator for the News Monitor + Signal System
#
#  Usage:
#    python main.py                    # full run, last 12 h
#    python main.py --hours 6          # last 6 h only
#    python main.py --top 20           # process top 20 news items
#    python main.py --no-prices        # skip live price fetch (faster)
#    python main.py --loop 30          # refresh every 30 minutes
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import argparse
import time
import sys

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from news_fetcher   import fetch_all_feeds, deduplicate, NewsItem
from sentiment_analyzer import analyze as analyze_sentiment, SentimentResult
from stock_mapper   import map_stocks
from impact_analyzer import analyze_impact, ImpactResult
from signal_engine  import generate_signal, TradeSignal
from dashboard      import (
    console,
    render_header,
    render_news_card,
    render_impact_table,
    render_signal,
    render_top5_impacted,
    render_top3_underreacted,
    render_sector_rotation,
    render_footer,
)

# ── Impact-strength priority for ranking ──────────────────────
_IMPACT_ORDER = {"EXTREME": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}


def run_analysis(hours: int = 12, top_n: int = 25, fetch_prices: bool = True):
    """Main analysis pipeline."""
    render_header()

    # ── Step 1: Fetch News ────────────────────────────────────
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=True) as prog:
        t = prog.add_task("Fetching news feeds...", total=None)
        raw_items = fetch_all_feeds(hours_back=hours, max_per_feed=30)
        prog.update(t, description=f"Fetched {len(raw_items)} articles")

    items = deduplicate(raw_items)
    console.print(f"  [dim]Loaded [white]{len(items)}[/] unique articles (deduped from {len(raw_items)}) — last {hours}h[/]\n")

    if not items:
        console.print("[yellow]  No news articles found. Check your internet connection or try --hours 24[/]")
        return

    # ── Step 2: NLP + Impact per news item ───────────────────
    all_impacts: list[tuple[NewsItem, SentimentResult, list[ImpactResult]]] = []
    all_signals: list[tuple[NewsItem, ImpactResult, TradeSignal]] = []
    underreacted_ops: list[tuple[NewsItem, ImpactResult, TradeSignal]] = []

    # Rank news by relevance before processing
    items_to_process = items[:top_n]

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(bar_width=30),
        TaskProgressColumn(),
        console=console,
        transient=True,
    ) as prog:
        t = prog.add_task("Analysing news & fetching prices...", total=len(items_to_process))

        for item in items_to_process:
            sentiment = analyze_sentiment(item)

            # Skip genuinely neutral / irrelevant items early
            if abs(sentiment.score) < 0.03 and not sentiment.macro_sectors:
                prog.advance(t)
                continue

            matches = map_stocks(item, sentiment)
            if not matches:
                prog.advance(t)
                continue

            impacts = analyze_impact(
                item, sentiment, matches,
                max_stocks=8,
                fetch_prices=fetch_prices,
            )

            all_impacts.append((item, sentiment, impacts))

            for imp in impacts:
                sig = generate_signal(imp)
                if sig:
                    all_signals.append((item, imp, sig))
                    if imp.reaction_status == "Underreacted":
                        underreacted_ops.append((item, imp, sig))

            prog.advance(t)

    # ── Step 3: Sort by impact strength ──────────────────────
    all_impacts.sort(
        key=lambda x: max((_IMPACT_ORDER.get(r.impact_strength, 0) for r in x[2]), default=0),
        reverse=True,
    )

    # ── Step 4: Render per-news cards (top 8) ─────────────────
    console.rule("[bold]📰 Top News & Impact Analysis", style="blue")
    console.print()

    for idx, (item, sentiment, impacts) in enumerate(all_impacts[:8], 1):
        render_news_card(item, sentiment, idx)
        if impacts:
            render_impact_table(impacts[:6])

        # Show signals for this item
        for imp in impacts[:4]:
            sig = generate_signal(imp)
            if sig and sig.confidence >= 45:
                render_signal(sig, is_underreaction=(imp.reaction_status == "Underreacted"))

        console.print()

    # ── Step 5: Top-5 most impacted stocks ───────────────────
    flat_impacts: list[tuple[str, ImpactResult]] = []
    for item, _, impacts in all_impacts:
        for r in impacts:
            if r.relation == "Direct":
                flat_impacts.append((item.title[:45], r))

    # De-dup by symbol, keep highest impact
    seen: dict[str, tuple[str, ImpactResult]] = {}
    for headline, r in flat_impacts:
        if r.symbol not in seen or (
            _IMPACT_ORDER.get(r.impact_strength, 0) > _IMPACT_ORDER.get(seen[r.symbol][1].impact_strength, 0)
        ):
            seen[r.symbol] = (headline, r)

    top5 = sorted(seen.values(), key=lambda x: (
        _IMPACT_ORDER.get(x[1].impact_strength, 0),
        abs(x[1].actual_move_pct)
    ), reverse=True)

    if top5:
        console.rule("[bold]🔥 Rankings & Opportunities", style="red")
        console.print()
        render_top5_impacted(top5)
        console.print()

    # ── Step 6: Top-3 underreacted opportunities ─────────────
    underreacted_ops.sort(
        key=lambda x: (x[2].confidence, abs(x[1].expected_move_pct - x[1].actual_move_pct)),
        reverse=True,
    )
    if underreacted_ops:
        render_top3_underreacted(underreacted_ops)

    # ── Step 7: Sector rotation ───────────────────────────────
    if flat_impacts:
        render_sector_rotation(flat_impacts)
        console.print()

    # ── Step 8: Footer summary ────────────────────────────────
    render_footer(
        total_news=len(items),
        total_signals=len(all_signals),
        underreacted=len(underreacted_ops),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Real-Time News Monitor + Stock Impact + Trading Signals"
    )
    parser.add_argument("--hours",      type=int,   default=12,    help="Hours of news to look back (default 12)")
    parser.add_argument("--top",        type=int,   default=25,    help="Max news items to analyse (default 25)")
    parser.add_argument("--no-prices",  action="store_true",        help="Skip live price fetch (faster demo mode)")
    parser.add_argument("--loop",       type=int,   default=0,      help="Refresh interval in minutes (0 = run once)")
    args = parser.parse_args()

    if args.loop > 0:
        console.print(f"[dim]Running in loop mode — refreshing every {args.loop} minutes. Ctrl+C to stop.[/]\n")
        while True:
            try:
                run_analysis(
                    hours=args.hours,
                    top_n=args.top,
                    fetch_prices=not args.no_prices,
                )
                console.print(f"[dim]Next refresh in {args.loop} min…[/]")
                time.sleep(args.loop * 60)
            except KeyboardInterrupt:
                console.print("\n[yellow]Stopped.[/]")
                sys.exit(0)
    else:
        run_analysis(
            hours=args.hours,
            top_n=args.top,
            fetch_prices=not args.no_prices,
        )


if __name__ == "__main__":
    main()
