# ─────────────────────────────────────────────────────────────
#  news_fetcher.py  –  Fetch and parse RSS feeds
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import feedparser
import requests
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateparser
from dataclasses import dataclass, field
from typing import Optional
import time

from config import NEWS_FEEDS


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


def fetch_all_feeds(hours_back: int = 12, max_per_feed: int = 20) -> list[NewsItem]:
    """
    Fetch articles from all configured RSS feeds published within
    the last `hours_back` hours.
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
            print(f"  [WARN] Feed '{source_name}' failed: {exc}")

        time.sleep(0.3)   # polite crawl delay

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
