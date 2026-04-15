# ─────────────────────────────────────────────────────────────
#  news_fetcher.py  –  Fetch and parse RSS feeds + API sources
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import feedparser
import logging
import requests
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateparser
from dataclasses import dataclass, field
from typing import Optional
import time

from config import NEWS_FEEDS

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    title: str
    summary: str
    source: str
    url: str
    published: datetime
    full_text: str = ""       # Populated if article body is fetched
    raw_text: str = ""        # title + summary combined for NLP

    def __post_init__(self):
        self.raw_text = f"{self.title}. {self.summary}".lower()


def _parse_date(entry) -> datetime:
    """Best-effort date parsing from a feedparser entry."""
    for attr in ("published", "updated", "created"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                return dateparser.parse(raw).replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return datetime.now(tz=timezone.utc)


def _clean_html(text: str) -> str:
    """Strip HTML tags from text."""
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    except Exception:
        import re
        return re.sub(r"<[^>]+>", " ", text)


def fetch_tradingview_economics_news(hours_back: int = 12, limit: int = 20) -> list[NewsItem]:
    """Fetch Trading Economics news from TradingView's internal headlines API."""
    url = (
        "https://news-headlines.tradingview.com/headlines/"
        f"?provider=trading-economics&lang=en&limit={limit}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; FinNewsBot/1.0)",
        "Accept": "application/json",
        "Referer": "https://in.tradingview.com/",
    }
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)
    items: list[NewsItem] = []

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # API returns a plain list of headline objects
        stories = data if isinstance(data, list) else data.get("items", [])

        for story in stories:
            pub_ts = story.get("published", 0)
            pub_dt = (
                datetime.fromtimestamp(pub_ts, tz=timezone.utc)
                if pub_ts else datetime.now(tz=timezone.utc)
            )
            if pub_dt < cutoff:
                continue

            title   = (story.get("title", "") or "").strip()
            summary = (story.get("shortDescription", "") or story.get("description", "") or "").strip()
            link    = story.get("link", "") or story.get("storyPath", "")
            # Normalize relative storyPath URLs
            if link and link.startswith("/"):
                link = f"https://in.tradingview.com{link}"
            if not title:
                continue

            items.append(NewsItem(
                title=title,
                summary=summary[:600],
                source="TradingView - Trading Economics",
                url=link,
                published=pub_dt,
            ))

    except Exception as exc:
        logger.warning("TradingView Economics fetch failed: %s", exc)

    return items


def fetch_all_feeds(hours_back: int = 12, max_per_feed: int = 20) -> list[NewsItem]:
    """
    Fetch articles from all configured RSS feeds and the TradingView Economics
    API, published within the last `hours_back` hours.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)
    all_items: list[NewsItem] = []
    seen_urls: set[str] = set()

    for source_name, feed_url in NEWS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url, request_headers={
                "User-Agent": "Mozilla/5.0 (compatible; FinNewsBot/1.0)"
            })
            entries = feed.entries[:max_per_feed]

            for entry in entries:
                url = getattr(entry, "link", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                title   = _clean_html(getattr(entry, "title",   ""))
                summary = _clean_html(getattr(entry, "summary", "") or
                                      getattr(entry, "description", ""))
                pub_dt  = _parse_date(entry)

                if pub_dt < cutoff:
                    continue

                item = NewsItem(
                    title=title,
                    summary=summary[:600],
                    source=source_name,
                    url=url,
                    published=pub_dt,
                )
                all_items.append(item)

        except Exception as exc:
            # Silently skip feeds that fail; don't crash the system
            logger.warning("Feed '%s' failed: %s", source_name, exc)

        time.sleep(0.3)   # polite crawl delay

    # Trading Economics via TradingView internal API (no RSS available)
    te_items = fetch_tradingview_economics_news(hours_back=hours_back, limit=max_per_feed)
    for item in te_items:
        if item.url and item.url in seen_urls:
            continue
        if item.url:
            seen_urls.add(item.url)
        all_items.append(item)
    logger.info("TradingView Economics: %d articles", len(te_items))

    # Sort newest first
    all_items.sort(key=lambda x: x.published, reverse=True)
    return all_items


def deduplicate(items: list[NewsItem], similarity_threshold: float = 0.65) -> list[NewsItem]:
    """
    Remove near-duplicate headlines using word-overlap Jaccard similarity.
    """
    def tokenize(text: str) -> set[str]:
        import re
        return set(re.findall(r"\b\w{4,}\b", text.lower()))

    unique: list[NewsItem] = []
    seen_tokens: list[set[str]] = []

    for item in items:
        tokens = tokenize(item.title)
        is_dup = False
        for prev_tokens in seen_tokens:
            if not tokens or not prev_tokens:
                continue
            jaccard = len(tokens & prev_tokens) / len(tokens | prev_tokens)
            if jaccard >= similarity_threshold:
                is_dup = True
                break
        if not is_dup:
            unique.append(item)
            seen_tokens.append(tokens)

    return unique
