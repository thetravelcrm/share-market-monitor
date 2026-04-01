# ─────────────────────────────────────────────────────────────
#  impact_analyzer.py  –  Fetch live prices + quantify impact
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import logging
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
logger = logging.getLogger(__name__)


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
    lot_size: int  = 1    # MCX contract lot size in base unit (1 for NSE stocks)
    lot_unit: str  = ""   # e.g. "kg", "g", "bbl" — empty for NSE stocks


# ── MCX commodity config (module-level for shared access) ─────
_MCX_PROXY: dict[str, str] = {
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

_MCX_LOT_SIZES: dict[str, tuple[int, str]] = {
    "SILVERMIC":  (1,    "kg"),   # Silver Micro: Trading Unit = 1 kg (MCX spec)
    "GOLDM":      (10,   "g"),
    "CRUDEOIL":   (100,  "bbl"),
    "NATURALGAS": (1250, "mmbtu"),
    "COPPER":     (250,  "kg"),
    "ZINC":       (5000, "kg"),
    "ALUMINIUM":  (5000, "kg"),
    "NICKEL":     (250,  "kg"),
    "LEAD":       (5000, "kg"),
}

# Conversion: COMEX price (USD/troy oz) → MCX price (INR/unit)
# 1 troy oz = 31.1035 g → 1 kg = 1000/31.1035 = 32.1507 troy oz
_MCX_CONV: dict[str, float] = {
    "SILVERMIC": 32.1507,   # USD/oz × oz_per_kg × USD/INR = INR/kg
    "GOLDM":     0.0321507, # USD/oz × oz_per_g  × USD/INR = INR/g
}

# MCX local premium over COMEX×USD/INR.
# Silver has ~8% effective import duty premium (BCD 6% + AIDC 5% + basis diff).
# Gold matches without correction (duty structure already reflected in spot benchmark).
# Calibrated: MCX_actual / (COMEX × oz_factor × USD/INR) as of 2026-04
_MCX_LOCAL_PREMIUM: dict[str, float] = {
    "SILVERMIC": 1.083,   # ~8.3% import duty + basis vs COMEX SI=F
}


_usd_inr_cache: dict = {"rate": 84.0, "fetched_at": 0.0}


def _fetch_usd_inr() -> float:
    """Fetch live USD/INR rate with 1-hour cache. Falls back to last good rate."""
    now = time.time()
    if now - _usd_inr_cache["fetched_at"] < 3600:
        return _usd_inr_cache["rate"]
    try:
        rate = yf.Ticker("USDINR=X").fast_info.last_price
        if rate and 60 < rate < 120:
            _usd_inr_cache["rate"] = float(rate)
            _usd_inr_cache["fetched_at"] = now
            return float(rate)
        logger.warning("USD/INR rate out of range (%.2f), using cached %.2f",
                       rate or 0, _usd_inr_cache["rate"])
    except Exception as exc:
        logger.warning("USD/INR fetch failed (%s), using cached %.2f",
                       exc, _usd_inr_cache["rate"])
    return _usd_inr_cache["rate"]


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
    news_type: str = "Ongoing"          # "Breaking" | "Ongoing" | "Rumor"


def _validate_price_data(current: float, prev: float, day_vol: int, symbol: str) -> bool:
    """Return False if price data looks stale, corrupted, or nonsensical."""
    if current <= 0 or prev <= 0:
        logger.warning("%s: zero/negative price (curr=%.2f, prev=%.2f)", symbol, current, prev)
        return False
    if day_vol == 0:
        logger.warning("%s: zero volume — market closed or data stale", symbol)
        return False
    daily_change = abs(current - prev) / prev * 100
    if daily_change > 30:
        logger.warning("%s: suspicious %.1f%% daily move — possible data error", symbol, daily_change)
        return False
    return True


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
                except Exception as exc:
                    logger.debug("Fyers yfinance supplement failed for %s: %s", symbol, exc)
                vol_ratio = round(fq["volume"] / avg_vol, 2) if avg_vol > 0 else 1.0
                if not _validate_price_data(fq["last_price"], fq["prev_close"], fq["volume"], symbol):
                    return None
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
        except Exception as exc:
            logger.debug("Fyers quote failed for %s: %s — falling back to yfinance", symbol, exc)

    # ── Resolve ticker symbol ──────────────────────────────────
    is_mcx = symbol in _MCX_PROXY
    ticker_sym = _MCX_PROXY[symbol] if is_mcx else f"{symbol}.NS"

    try:
        tk   = yf.Ticker(ticker_sym)
        hist = tk.history(period="60d", interval="1d", auto_adjust=True)

        if hist.empty or len(hist) < 2:
            return None

        # Prefer fast_info for live/intraday price; fall back to last daily close
        try:
            _fi = tk.fast_info
            _live = float(_fi.last_price) if getattr(_fi, "last_price", None) else 0.0
            _prev_close = float(_fi.previous_close) if getattr(_fi, "previous_close", None) else 0.0
            comex_price = _live if _live > 0 else float(hist["Close"].iloc[-1])
            comex_prev  = _prev_close if _prev_close > 0 else float(hist["Close"].iloc[-2])
        except Exception:
            comex_price = float(hist["Close"].iloc[-1])
            comex_prev  = float(hist["Close"].iloc[-2])

        # ── MCX metals: convert COMEX (USD/oz) → MCX (INR/unit) ───
        if symbol in _MCX_CONV:
            usd_inr  = _fetch_usd_inr()
            conv     = _MCX_CONV[symbol]
            premium  = _MCX_LOCAL_PREMIUM.get(symbol, 1.0)
            current  = round(comex_price * conv * usd_inr * premium, 2)
            prev     = round(comex_prev  * conv * usd_inr * premium, 2)
            h52w     = round(float(hist["High"].max()) * conv * usd_inr * premium, 2)
            l52w     = round(float(hist["Low"].min())  * conv * usd_inr * premium, 2)
            currency = "INR"
        elif is_mcx:
            current  = comex_price
            prev     = comex_prev
            h52w     = float(hist["High"].max())
            l52w     = float(hist["Low"].min())
            currency = "USD"
        else:
            current  = comex_price
            prev     = comex_prev
            h52w     = float(hist["High"].max())
            l52w     = float(hist["Low"].min())
            currency = "INR"

        day_chg   = round((current - prev) / prev * 100, 2)
        day_vol   = int(hist["Volume"].iloc[-1])
        avg_vol   = int(hist["Volume"].iloc[-20:].mean()) if len(hist) >= 20 else day_vol
        vol_ratio = round(day_vol / avg_vol, 2) if avg_vol > 0 else 1.0

        # Technicals computed on raw COMEX prices (scale-invariant ratios: RSI, MACD, Stoch)
        tech = compute_technicals(hist, comex_price)

        info = tk.fast_info
        mktcap_raw = getattr(info, "market_cap", 0) or 0
        mktcap_cr  = round(mktcap_raw / 1e7, 0)

        lot_s, lot_u = _MCX_LOT_SIZES.get(symbol, (1, ""))

        if not _validate_price_data(current, prev, day_vol, symbol):
            return None

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
            lot_size=lot_s,
            lot_unit=lot_u,
        )
    except Exception as exc:
        logger.error("Price fetch failed for %s: %s", symbol, exc)
        return None


def _calculate_impact_strength(
    sentiment: SentimentResult,
    match: StockMatch,
) -> tuple[str, float]:
    score = abs(sentiment.score)

    if match.relation == "Direct":
        # Direct mention: amplify + allow category boost → can reach EXTREME
        score = min(1.0, score * 1.4)
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
    elif match.relation == "Sectoral":
        # Sector peer: dampen + cap at HIGH (0.75) — can never be EXTREME
        score = min(0.75, score * 0.7)
    elif match.relation == "Macro":
        # Macro cascade: heavily dampen + cap at MEDIUM (0.55)
        score = min(0.55, score * 0.45)

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
            news_type=getattr(sentiment, "news_type", "Ongoing"),
        ))

    order = {"EXTREME": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    results.sort(key=lambda x: (order.get(x.impact_strength, 4), x.relation != "Direct"))
    return results
