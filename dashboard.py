# ─────────────────────────────────────────────────────────────
#  dashboard.py  –  Rich terminal dashboard renderer
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.rule import Rule
from rich import box
from rich.align import Align

from news_fetcher import NewsItem
from sentiment_analyzer import SentimentResult
from impact_analyzer import ImpactResult
from signal_engine import TradeSignal

console = Console(width=130)

# ── Colour helpers ────────────────────────────────────────────
_IMPACT_COLOR  = {"EXTREME": "bright_red", "HIGH": "red", "MEDIUM": "yellow", "LOW": "green"}
_SENT_COLOR    = {"Positive": "bright_green", "Negative": "bright_red", "Neutral": "yellow"}
_ACTION_COLOR  = {"BUY": "bright_green", "SHORT": "bright_red", "SELL": "red", "AVOID": "dim"}
_REACT_COLOR   = {"Underreacted": "bright_cyan", "Overreacted": "yellow", "Reacted": "white"}
_REACT_ICON    = {"Underreacted": "👉 UNDERREACTED", "Overreacted": "⚠️  OVERREACTED", "Reacted": "✅ REACTED"}


def _chg_str(pct: float) -> Text:
    s = f"{pct:+.2f}%"
    return Text(s, style="bright_green" if pct >= 0 else "bright_red")


def render_header():
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d  %H:%M UTC")
    console.print()
    console.print(Panel(
        Align.center(
            "[bold bright_white]📡  REAL-TIME NEWS MONITOR  |  STOCK IMPACT SYSTEM  |  TRADING SIGNALS[/]\n"
            f"[dim]{now}  —  NSE/BSE + Global Majors[/]"
        ),
        style="bold blue",
        box=box.DOUBLE_EDGE,
    ))
    console.print()


def render_news_card(
    item: NewsItem,
    sentiment: SentimentResult,
    index: int,
):
    sc = _SENT_COLOR.get(sentiment.label, "white")
    title_text = Text(item.title[:110], style="bold white")
    meta = (
        f"[dim]Source:[/dim] [cyan]{item.source}[/]  "
        f"[dim]|[/dim]  [dim]Category:[/dim] [magenta]{sentiment.category}[/]  "
        f"[dim]|[/dim]  [dim]Sentiment:[/dim] [{sc}]{sentiment.label} ({sentiment.score:+.2f})[/]  "
        f"[dim]|[/dim]  [dim]{item.published.strftime('%H:%M')}[/]"
    )
    console.print(Panel(
        f"{title_text}\n{meta}",
        title=f"[bold dim]#{index}[/]",
        border_style="blue",
        box=box.ROUNDED,
        padding=(0, 1),
    ))


def render_impact_table(impacts: list[ImpactResult]):
    tbl = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold dim",
        expand=True,
        pad_edge=False,
    )
    tbl.add_column("Symbol",    style="bold white",  width=12)
    tbl.add_column("Name",      style="white",        width=20)
    tbl.add_column("Sector",    style="cyan",         width=16)
    tbl.add_column("Relation",  width=10)
    tbl.add_column("Impact",    width=9)
    tbl.add_column("Expected",  width=10, justify="right")
    tbl.add_column("Actual",    width=10, justify="right")
    tbl.add_column("Vol Ratio", width=9,  justify="right")
    tbl.add_column("Status",    width=20)

    for r in impacts:
        ic  = _IMPACT_COLOR.get(r.impact_strength, "white")
        rc  = _REACT_COLOR.get(r.reaction_status, "white")
        rel_style = "bright_white" if r.relation == "Direct" else ("dim white" if r.relation == "Macro" else "white")
        tbl.add_row(
            r.symbol,
            r.name[:18],
            r.sector[:14],
            Text(r.relation, style=rel_style),
            Text(r.impact_strength, style=ic),
            Text(f"{r.expected_move_pct:+.1f}%", style="dim white"),
            _chg_str(r.actual_move_pct),
            Text(f"{r.volume_ratio:.1f}x", style="bright_white" if r.volume_ratio >= 1.5 else "dim"),
            Text(_REACT_ICON.get(r.reaction_status, r.reaction_status), style=rc),
        )

    console.print(Panel(tbl, title="[bold]📊 Impact Analysis", border_style="cyan", box=box.ROUNDED))


def render_signal(signal: TradeSignal, is_underreaction: bool = False):
    ac   = _ACTION_COLOR.get(signal.action, "white")
    conf_bar = "█" * (signal.confidence // 10) + "░" * (10 - signal.confidence // 10)
    conf_col = "bright_green" if signal.confidence >= 70 else ("yellow" if signal.confidence >= 50 else "red")

    price_info = ""
    if signal.entry_low > 0:
        price_info = (
            f"  [dim]Entry:[/]  [bold]{signal.entry_low:.2f} – {signal.entry_high:.2f}[/]\n"
            f"  [dim]SL   :[/]  [bright_red]{signal.stop_loss:.2f}[/]   "
            f"  [dim]T1:[/] [green]{signal.target1:.2f}[/]   "
            f"  [dim]T2:[/] [bright_green]{signal.target2:.2f}[/]\n"
            f"  [dim]R:R  :[/]  [bold]{signal.risk_reward:.1f}x[/]   "
            f"  [dim]Horizon:[/] {signal.time_horizon}"
        )

    badge = "  [bold bright_cyan]★ UNDERREACTION OPPORTUNITY[/]" if is_underreaction else ""

    content = (
        f"  [{ac}][bold]{signal.action}  {signal.symbol}[/][/]  "
        f"[dim]–[/] [white]{signal.name}[/]{badge}\n"
        f"  [dim]Confidence:[/] [{conf_col}]{conf_bar} {signal.confidence}%[/]\n"
        + price_info +
        f"\n  [dim italic]{signal.rationale}[/]"
    )

    border = "bright_cyan" if is_underreaction else ac.replace("bright_", "")
    console.print(Panel(content, title=f"[bold]💰 Trade Signal – {signal.edge_type}", border_style=border, box=box.ROUNDED))


def render_top5_impacted(impacts_all: list[tuple[str, ImpactResult]]):
    """impacts_all: list of (headline_snippet, ImpactResult)."""
    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", expand=True)
    tbl.add_column("#",       width=3,  justify="right")
    tbl.add_column("Symbol",  width=12, style="bold white")
    tbl.add_column("Name",    width=22)
    tbl.add_column("Impact",  width=9)
    tbl.add_column("Actual",  width=10, justify="right")
    tbl.add_column("Expected",width=10, justify="right")
    tbl.add_column("Sentiment",width=10)
    tbl.add_column("Top News", width=45, style="dim")

    for i, (headline, r) in enumerate(impacts_all[:5], 1):
        ic = _IMPACT_COLOR.get(r.impact_strength, "white")
        sc = _SENT_COLOR.get(r.sentiment_label, "white")
        tbl.add_row(
            str(i),
            r.symbol,
            r.name[:20],
            Text(r.impact_strength, style=ic),
            _chg_str(r.actual_move_pct),
            Text(f"{r.expected_move_pct:+.1f}%", style="dim"),
            Text(r.sentiment_label[:8], style=sc),
            headline[:43],
        )
    console.print(Panel(tbl, title="[bold]🔥 Top 5 Most Impacted Stocks Today", border_style="red", box=box.ROUNDED))


def render_top3_underreacted(opportunities: list[tuple[NewsItem, ImpactResult, TradeSignal]]):
    console.print(Panel(
        "  [bold bright_cyan]Top 3 Hidden Opportunities — UNDERREACTED stocks[/]\n"
        "  [dim]News impact >> price movement. Volume yet to confirm. Smart money window.[/]",
        border_style="bright_cyan",
        box=box.ROUNDED,
        padding=(0, 1),
    ))
    for i, (item, impact, signal) in enumerate(opportunities[:3], 1):
        console.print(
            f"  [bold cyan]{i}.[/] [bold white]{signal.symbol}[/] — [white]{signal.name}[/]  "
            f"[dim]|[/] Expected [yellow]{impact.expected_move_pct:+.1f}%[/]  "
            f"[dim]Actual[/] {_chg_str(impact.actual_move_pct)}  "
            f"[dim]Vol[/] [white]{impact.volume_ratio:.1f}x[/]  "
            f"[dim]Signal[/] [{_ACTION_COLOR.get(signal.action,'white')}]{signal.action}[/]  "
            f"[dim]Conf[/] [bright_green]{signal.confidence}%[/]"
        )
        console.print(f"     [dim italic]{item.title[:100]}[/]")
        console.print()


def render_sector_rotation(impacts_all: list[tuple[str, ImpactResult]]):
    sector_scores: dict[str, list[float]] = {}
    for _, r in impacts_all:
        sector_scores.setdefault(r.sector, []).append(r.actual_move_pct)

    if not sector_scores:
        return

    sector_avg = {s: sum(v) / len(v) for s, v in sector_scores.items() if len(v) >= 1}
    sorted_sectors = sorted(sector_avg.items(), key=lambda x: x[1], reverse=True)

    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", expand=False)
    tbl.add_column("Sector",        width=24, style="white")
    tbl.add_column("Avg Move",      width=10, justify="right")
    tbl.add_column("# Stocks",      width=9,  justify="center")
    tbl.add_column("Trend",         width=20)

    for sector, avg in sorted_sectors[:10]:
        count = len(sector_scores[sector])
        bar_len = min(15, int(abs(avg) * 2))
        if avg >= 0:
            bar = Text("▲ " + "▬" * bar_len, style="bright_green")
        else:
            bar = Text("▼ " + "▬" * bar_len, style="bright_red")
        tbl.add_row(sector, _chg_str(avg), str(count), bar)

    console.print(Panel(tbl, title="[bold]📈 Sector Rotation Trends", border_style="magenta", box=box.ROUNDED))


def render_footer(total_news: int, total_signals: int, underreacted: int):
    console.print(Rule(style="dim"))
    console.print(
        f"  [dim]Processed [white]{total_news}[/] news items  |  "
        f"[white]{total_signals}[/] signals generated  |  "
        f"[bright_cyan]{underreacted}[/] underreaction opportunities[/]"
    )
    console.print()
