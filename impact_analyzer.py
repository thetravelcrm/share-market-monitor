# ─────────────────────────────────────────────────────────────
#  impact_analyzer.py  –  Fetch live prices + quantify impact
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import time
import warnings
from dataclasses import dataclass, field
from typing import Optional

import yfinance as yf
import pandas as pd
import numpy as np

from config import IMPACT_THRESHOLDS, HISTORICAL_REACTIONS, UNDERREACTION
from news_fetcher import NewsItem
from sentiment_analyzer import SentimentResult
from stock_mapper import StockMatch
from technical_analyzer import TechnicalData, compute_technicals

warnings.filterwarnings("ignore")


@dataclass
class PriceData:
    symbol: str
    current_price: float
    prev_close: float
    day_change_pct: float
    day_volume: int
    avg_volume_20d: int
    volume_ratio: float
    high_52w: float
    low_52w: float
    market_cap_cr: float    # in crore INR (or USD for globals)
    currency: str
    technical: Optional[TechnicalData] = None   # RSI, SMA, support/resistance


@dataclass
class ImpactResult:
    symbol: str
    name: str
    sector: str
    relation: str
    sentiment_label: str
    impact_strength: str       # LOW / MEDIUM / HIGH / EXTREME
    expected_move_pct: float   # expected % move based on history + NLP
    actual_move_pct: float     # today's actual % change
    volume_ratio: float
    reaction_status: str       # "Reacted" | "Underreacted" | "Overreacted"
    price_data: Optional[PriceData] = None
    notes: str = ""


def _fetch_price(symbol: str, exchange: str = "NSE") -> Optional[PriceData]:
    """Fetch live/latest price data. Uses Fyers API if connected, else yfinance."""
    _MCX_SYMBOLS = {"SILVERMIC","GOLDM","CRUDEOIL","NATURALGAS","COPPER","ZINC","ALUMINIUM","NICKEL","LEAD"}

    # ── Try Fyers for NSE stocks ───────────────────────────────
    if symbol not in _MCX_SYMBOLS:
        try:
            import streamlit as _st
            _token = _st.session_state.get("fyers_token", "")
            from fyers_fetcher import get_quote
            fq = get_quote(symbol, _token) if _token else None
            if fq:
                avg_vol = fq["volume"]
                h52w = fq["high"]; l52w = fq["low"]
                tech = None
                try:
                    _h = yf.Ticker(f"{symbol}.NS").history(period="60d", interval="1d", auto_adjust=True)
                    if len(_h) >= 20:
                        avg_vol = int(_h["Volume"].iloc[-20:].mean())
                        h52w = float(_h["High"].max())
                        l52w = float(_h["Low"].min())
                        tech = compute_technicals(_h, fq["last_price"])
                except Exception:
                    pass
                vol_ratio = round(fq["volume"] / avg_vol, 2) if avg_vol > 0 else 1.0
                return PriceData(
                    symbol=symbol,
                    current_price=round(fq["last_price"], 2),
                    prev_close=round(fq["prev_close"], 2),
                    day_change_pct=fq["change_pct"],
                    day_volume=fq["volume"],
                    avg_volume_20d=avg_vol,
                    volume_ratio=vol_ratio,
                    high_52w=round(h52w, 2),
                    low_52w=round(l52w, 2),
                    market_cap_cr=0,
                    currency="INR",
                    technical=tech,
                )
        except Exception:
            pass  # fall through to yfinance

    # ── MCX commodity futures → COMEX proxies ─────────────────
    _MCX_PROXY = {
        "SILVERMIC":  "SI=F",
        "GOLDM":      "GC=F",
        "CRUDEOIL":   "CL=F",
        "NATURALGAS": "NG=F",
        "COPPER":     "HG=F",
        "ZINC":       "ZNC=F",
        "ALUMINIUM":  "ALI=F",
        "NICKEL":     "NI=F",
        "LEAD":       "LE=F",
    }
    if symbol in _MCX_PROXY:
        ticker_sym = _MCX_PROXY[symbol]
        currency = "USD"
    else:
        ticker_sym = f"{symbol}.NS"
        currency = "INR"

    try:
        tk   = yf.Ticker(ticker_sym)
        hist = tk.history(period="60d", interval="1d", auto_adjust=True)

        if hist.empty or len(hist) < 2:
            return None

        current   = float(hist["Close"].iloc[-1])
        prev      = float(hist["Close"].iloc[-2])
        day_chg   = round((current - prev) / prev * 100, 2)
        day_vol   = int(hist["Volume"].iloc[-1])
        avg_vol   = int(hist["Volume"].iloc[-20:].mean()) if len(hist) >= 20 else day_vol
        vol_ratio = round(day_vol / avg_vol, 2) if avg_vol > 0 else 1.0
        h52w      = float(hist["High"].max())
        l52w      = float(hist["Low"].min())

        info = tk.fast_info
        mktcap_raw = getattr(info, "market_cap", 0) or 0
        mktcap_cr  = round(mktcap_raw / 1e7, 0)

        tech = compute_technicals(hist, current)

        return PriceData(
            symbol=symbol,
            current_price=round(current, 2),
            prev_close=round(prev, 2),
            day_change_pct=day_chg,
            day_volume=day_vol,
            avg_volume_20d=avg_vol,
            volume_ratio=vol_ratio,
            high_52w=round(h52w, 2),
            low_52w=round(l52w, 2),
            market_cap_cr=mktcap_cr,
            currency=currency,
            technical=tech,
        )
    except Exception:
        return None


def _calculate_impact_strength(
    sentiment: SentimentResult,
    match: StockMatch,
) -> tuple[str, float]:
    score = abs(sentiment.score)
    if match.relation == "Direct":
        score = min(1.0, score * 1.4)
    elif match.relation == "Sectoral":
        score = min(1.0, score * 0.8)
    elif match.relation == "Macro":
        score = min(1.0, score * 0.5)

    category_boost = {
        "Earnings":     0.15,
        "Company":      0.12,
        "Regulatory":   0.10,
        "Macro":        0.05,
        "Geopolitical": 0.08,
        "Sector":       0.04,
        "General":      0.0,
    }
    score = min(1.0, score + category_boost.get(sentiment.category, 0))

    for label, threshold in IMPACT_THRESHOLDS.items():
        if score >= threshold:
            return label, score
    return "LOW", score


def _expected_move(
    sentiment: SentimentResult,
    impact: str,
    match: StockMatch,
) -> float:
    key  = (sentiment.category, sentiment.label, impact)
    base = HISTORICAL_REACTIONS.get(key, None)
    if base is None:
        base = sentiment.score * 5.0
    dampener = {"Direct": 1.0, "Sectoral": 0.5, "Macro": 0.3}
    return round(base * dampener.get(match.relation, 0.5), 2)


def _reaction_status(expected: float, actual: float, vol_ratio: float) -> str:
    min_exp = UNDERREACTION["min_expected_move_pct"]
    max_act = UNDERREACTION["max_actual_move_pct"]
    vol_thr = UNDERREACTION["volume_threshold"]
    if abs(expected) >= min_exp and abs(actual) < max_act and vol_ratio < vol_thr:
        return "Underreacted"
    if abs(actual) > abs(expected) * 2.0:
        return "Overreacted"
    return "Reacted"


def analyze_impact(
    item: NewsItem,
    sentiment: SentimentResult,
    matches: list[StockMatch],
    max_stocks: int = 10,
    fetch_prices: bool = True,
) -> list[ImpactResult]:
    results: list[ImpactResult] = []

    for match in matches[:max_stocks]:
        impact_label, _ = _calculate_impact_strength(sentiment, match)
        expected_move   = _expected_move(sentiment, impact_label, match)

        price_data  = None
        actual_move = 0.0
        vol_ratio   = 1.0

        if fetch_prices:
            price_data = _fetch_price(match.symbol)
            if price_data:
                actual_move = price_data.day_change_pct
                vol_ratio   = price_data.volume_ratio
            time.sleep(0.2)

        reaction = _reaction_status(expected_move, actual_move, vol_ratio)

        results.append(ImpactResult(
            symbol=match.symbol,
            name=match.name,
            sector=match.sector,
            relation=match.relation,
            sentiment_label=sentiment.label,
            impact_strength=impact_label,
            expected_move_pct=expected_move,
            actual_move_pct=actual_move,
            volume_ratio=vol_ratio,
            reaction_status=reaction,
            price_data=price_data,
        ))

    order = {"EXTREME": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    results.sort(key=lambda x: (order.get(x.impact_strength, 4), x.relation != "Direct"))
    return results
