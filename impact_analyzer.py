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

# ── Price fetch cache — avoids duplicate yfinance calls within one analysis run ──
_price_cache: dict[str, tuple[float, Optional["PriceData"]]] = {}  # symbol → (timestamp, data)
_PRICE_CACHE_TTL = 300  # seconds (5 min)


def prefetch_prices(symbols: list[str]) -> None:
    """
    Batch-download price history for all symbols in a single yfinance request.
    Populates _price_cache so subsequent _fetch_price() calls are instant.
    Silently skips symbols that fail. Call once at the start of a pipeline run.
    """
    now = time.time()
    # Only fetch symbols not already in cache
    to_fetch = [s for s in symbols
                if s not in _price_cache or (now - _price_cache[s][0]) >= _PRICE_CACHE_TTL]
    if not to_fetch:
        return

    # Map NSE symbols → yfinance tickers
    tickers = [_MCX_PROXY.get(s, f"{s}.NS") for s in to_fetch]

    logger.info("Batch-prefetching %d symbols via yf.download()…", len(tickers))
    try:
        raw = yf.download(
            tickers,
            period="60d",
            interval="1d",
            auto_adjust=True,
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception as exc:
        logger.warning("Batch prefetch failed (%s) — falling back to per-symbol fetch", exc)
        return

    usd_inr = _fetch_usd_inr()

    for sym, ticker in zip(to_fetch, tickers):
        try:
            # Handle single vs multi-ticker download shape
            if len(tickers) == 1:
                hist = raw
            else:
                hist = raw[ticker] if ticker in raw.columns.get_level_values(0) else pd.DataFrame()

            hist = hist.dropna(how="all")
            if hist.empty or len(hist) < 2:
                _price_cache[sym] = (now, None)
                continue

            raw_price  = float(hist["Close"].iloc[-1])
            raw_prev   = float(hist["Close"].iloc[-2])

            # Apply MCX conversion
            if sym in _MCX_CONV:
                conv    = _MCX_CONV[sym]
                premium = _MCX_LOCAL_PREMIUM.get(sym, 1.0)
                current = round(raw_price * conv * usd_inr * premium, 2)
                prev    = round(raw_prev  * conv * usd_inr * premium, 2)
                h52w    = round(float(hist["High"].max()) * conv * usd_inr * premium, 2)
                l52w    = round(float(hist["Low"].min())  * conv * usd_inr * premium, 2)
                currency = "INR"
            elif sym in _MCX_PROXY:
                current  = raw_price;  prev = raw_prev
                h52w     = float(hist["High"].max())
                l52w     = float(hist["Low"].min())
                currency = "USD"
            else:
                current  = raw_price;  prev = raw_prev
                h52w     = float(hist["High"].max())
                l52w     = float(hist["Low"].min())
                currency = "INR"

            if current <= 0 or prev <= 0:
                _price_cache[sym] = (now, None)
                continue

            day_chg   = round((current - prev) / prev * 100, 2)
            day_vol   = int(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else 0
            avg_vol   = int(hist["Volume"].iloc[-20:].mean()) if len(hist) >= 20 and "Volume" in hist.columns else day_vol
            vol_ratio = round(day_vol / avg_vol, 2) if avg_vol > 0 else 1.0
            _skip_vol = sym in _MCX_PROXY
            if not _skip_vol and day_vol == 0:
                _price_cache[sym] = (now, None)
                continue

            tech      = compute_technicals(hist, raw_price)
            lot_s, lot_u = _MCX_LOT_SIZES.get(sym, (1, ""))

            _price_cache[sym] = (now, PriceData(
                symbol=sym,
                current_price=round(current, 2),
                prev_close=round(prev, 2),
                day_change_pct=day_chg,
                day_volume=day_vol,
                avg_volume_20d=avg_vol,
                volume_ratio=vol_ratio,
                high_52w=round(h52w, 2),
                low_52w=round(l52w, 2),
                market_cap_cr=0,
                currency=currency,
                technical=tech,
                lot_size=lot_s,
                lot_unit=lot_u,
            ))
        except Exception as exc:
            logger.debug("Prefetch parse failed for %s: %s", sym, exc)
            _price_cache[sym] = (now, None)

    logger.info("Prefetch complete — %d/%d symbols cached",
                sum(1 for s in to_fetch if _price_cache.get(s, (0, None))[1] is not None),
                len(to_fetch))


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
    "SILVERMIC":  "SI=F",    # COMEX Silver (USD/troy oz)
    "GOLDM":      "GC=F",    # COMEX Gold   (USD/troy oz)
    "CRUDEOIL":   "CL=F",    # NYMEX WTI Crude (USD/bbl)
    "NATURALGAS": "NG=F",    # NYMEX Nat Gas (USD/mmbtu)
    "COPPER":     "HG=F",    # COMEX Copper (USD/lb)
    "ALUMINIUM":  "ALI=F",   # CME Aluminium (USD/tonne)
    # ZINC/NICKEL/LEAD are LME-traded; no reliable COMEX yfinance proxy
}

_MCX_LOT_SIZES: dict[str, tuple[int, str]] = {
    "SILVERMIC":  (1,    "kg"),     # Silver Micro: 1 kg per lot (MCX spec)
    "GOLDM":      (1,    "10g"),   # Gold Mini: 10 g per lot (MCX spec); price quoted per 10g
    "CRUDEOIL":   (100,  "bbl"),   # Crude Oil: 100 barrels per lot
    "NATURALGAS": (1250, "mmbtu"), # Natural Gas: 1250 mmbtu per lot
    "COPPER":     (250,  "kg"),    # Copper: 250 kg per lot
    "ZINC":       (5000, "kg"),    # Zinc: 5000 kg per lot (no COMEX proxy)
    "ALUMINIUM":  (5000, "kg"),    # Aluminium: 5000 kg per lot
    "NICKEL":     (250,  "kg"),    # Nickel: 250 kg per lot (no COMEX proxy)
    "LEAD":       (5000, "kg"),    # Lead: 5000 kg per lot (no COMEX proxy)
}

# Conversion: COMEX/NYMEX price (USD/unit) → MCX price (INR/unit)
# Gold/Silver: troy oz → grams conversion needed.
# Crude/Gas/Copper/Aluminium: already in USD/native-unit, factor = 1.0 (just × USD/INR)
# 1 troy oz = 31.1035 g → 1 kg = 1000/31.1035 = 32.1507 troy oz
_MCX_CONV: dict[str, float] = {
    "SILVERMIC":  32.1507,   # USD/oz  × 32.1507 oz/kg    × USD/INR = INR/kg
    "GOLDM":       0.321507, # USD/oz  × (10g/31.1035g)   × USD/INR = INR/10g
    "CRUDEOIL":    1.0,      # USD/bbl × 1.0              × USD/INR = INR/bbl
    "NATURALGAS":  1.0,      # USD/mmbtu × 1.0            × USD/INR = INR/mmbtu
    "COPPER":      2.20462,  # USD/lb  × 2.20462 lb/kg    × USD/INR = INR/kg
    "ALUMINIUM":   0.001,    # USD/t   × (1 t/1000 kg)    × USD/INR = INR/kg
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
    match_reason: str = ""              # e.g. 'keyword: "mcx"' or 'sector peer: AMC/Wealth'


def _validate_price_data(current: float, prev: float, day_vol: int, symbol: str,
                         skip_volume: bool = False) -> bool:
    """Return False if price data looks stale, corrupted, or nonsensical."""
    if current <= 0 or prev <= 0:
        logger.warning("%s: zero/negative price (curr=%.2f, prev=%.2f)", symbol, current, prev)
        return False
    # MCX metals use COMEX futures as proxy — COMEX intraday volume is often 0;
    # skip volume check for these (price range already validated by COMEX plausibility)
    if not skip_volume and day_vol == 0:
        logger.warning("%s: zero volume — market closed or data stale", symbol)
        return False
    daily_change = abs(current - prev) / prev * 100
    if daily_change > 30:
        logger.warning("%s: suspicious %.1f%% daily move — possible data error", symbol, daily_change)
        return False
    return True


def _fetch_price(symbol: str, exchange: str = "NSE") -> Optional[PriceData]:
    """Fetch live/latest price data (cached 5 min). Uses Fyers API if connected, else yfinance."""
    # ── Cache check ───────────────────────────────────────────────
    cached = _price_cache.get(symbol)
    if cached is not None:
        ts, data = cached
        if time.time() - ts < _PRICE_CACHE_TTL:
            return data

    result = _fetch_price_uncached(symbol, exchange)
    _price_cache[symbol] = (time.time(), result)
    return result


def _fetch_price_uncached(symbol: str, exchange: str = "NSE") -> Optional[PriceData]:
    """Internal: actual price fetch without caching."""
    _MCX_SYMBOLS = {"SILVERMIC","GOLDM","CRUDEOIL","NATURALGAS","COPPER","ZINC","ALUMINIUM","NICKEL","LEAD"}

    # ── Try Fyers for NSE stocks (MCX metals use yfinance COMEX+premium below) ──
    is_mcx_comex = symbol in _MCX_CONV   # metals that need COMEX→MCX conversion
    if not is_mcx_comex:
        try:
            import streamlit as _st
            _token = _st.session_state.get("fyers_token", "")
            from fyers_fetcher import get_quote
            fq = get_quote(symbol, _token) if _token else None
            if fq:
                avg_vol = fq["volume"]
                h52w = fq["high"]; l52w = fq["low"]
                tech = None
                is_mcx_sym = symbol in _MCX_SYMBOLS
                try:
                    _proxy = _MCX_PROXY.get(symbol, f"{symbol}.NS")
                    _h = yf.Ticker(_proxy).history(period="60d", interval="1d", auto_adjust=True)
                    if len(_h) >= 20:
                        avg_vol = int(_h["Volume"].iloc[-20:].mean())
                        h52w = float(_h["High"].max())
                        l52w = float(_h["Low"].min())
                        tech = compute_technicals(_h, fq["last_price"])
                except Exception as exc:
                    logger.debug("Fyers yfinance supplement failed for %s: %s", symbol, exc)
                lot_s, lot_u = _MCX_LOT_SIZES.get(symbol, (1, "")) if is_mcx_sym else (1, "")
                vol_ratio = round(fq["volume"] / avg_vol, 2) if avg_vol > 0 else 1.0
                if _validate_price_data(fq["last_price"], fq["prev_close"], fq["volume"], symbol):
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
                        lot_size=lot_s,
                        lot_unit=lot_u,
                    )
                # validation failed — fall through to yfinance
        except Exception as exc:
            logger.debug("Fyers quote failed for %s: %s — falling back to yfinance", symbol, exc)

    # ── Resolve ticker symbol ──────────────────────────────────
    is_mcx = symbol in _MCX_PROXY
    ticker_sym = _MCX_PROXY[symbol] if is_mcx else f"{symbol}.NS"

    try:
        tk   = yf.Ticker(ticker_sym)
        hist = tk.history(period="60d", interval="1d", auto_adjust=True)
    except Exception as exc:
        logger.error("Price fetch failed for %s: %s", symbol, exc)
        return None

    try:
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

        # For all MCX proxy symbols (COMEX/NYMEX futures), intraday volume is often 0 — skip check
        _skip_vol = symbol in _MCX_PROXY
        if not _validate_price_data(current, prev, day_vol, symbol, skip_volume=_skip_vol):
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
    dampener = {"Direct": 1.0, "Sectoral": 0.7, "Macro": 0.5}
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
            match_reason=getattr(match, "match_reason", ""),
        ))

    order = {"EXTREME": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    results.sort(key=lambda x: (order.get(x.impact_strength, 4), x.relation != "Direct"))
    return results
