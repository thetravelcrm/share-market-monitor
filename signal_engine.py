# ─────────────────────────────────────────────────────────────
#  signal_engine.py  –  Generate BUY / SELL / SHORT / NO TRADE
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from config import RISK_REWARD_MIN, CONFIDENCE_FLOOR
from impact_analyzer import ImpactResult, PriceData

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    symbol: str
    name: str
    action: str              # BUY | SELL | SHORT | AVOID | NO TRADE
    entry_low: float
    entry_high: float
    stop_loss: float
    target1: float
    target2: float
    risk_reward: float
    confidence: int          # 0–100
    time_horizon: str        # Intraday | Short-term | Swing | Long-term
    edge_type: str           # "Underreaction" | "Momentum" | "Mean-Reversion" | "Macro"
    rationale: str


# ─────────────────────────────────────────────────────────────
#  Strict Trade Filter — rejects bad setups before scoring
# ─────────────────────────────────────────────────────────────

def _strict_filter(result: ImpactResult) -> Optional[str]:
    """Return rejection reason if trade should be blocked, else None."""
    pd = result.price_data
    tech = pd.technical if pd else None

    if not tech:
        return "No technical data available"

    # Only block truly dead volume (< 0.5x avg); volume_dry already catches this
    # Removing the < 1.0 gate — slightly below-average volume is normal on news days

    # Market regime must be favorable
    regime = getattr(tech, "market_regime", "Unknown")
    if regime == "LowLiquidity":
        return "Low liquidity — no reliable price action"
    # Sideways filter only blocks LOW/MEDIUM impact — HIGH/EXTREME news can break a sideways market
    if regime == "Sideways" and not tech.bb_squeeze:
        if result.impact_strength not in ("EXTREME", "HIGH"):
            return "Sideways market, no breakout setup"

    # News + Technical must not strongly contradict
    sent = result.sentiment_label
    if sent == "Positive" and tech.trend == "Downtrend" and not tech.near_support:
        _st = getattr(tech, "supertrend_bullish", None)
        if _st is False:
            return "Positive news contradicts downtrend + bearish SuperTrend"
    if sent == "Negative" and tech.trend == "Uptrend" and not tech.near_resistance:
        _st = getattr(tech, "supertrend_bullish", None)
        if _st is True:
            return "Negative news contradicts uptrend + bullish SuperTrend"

    # Volume dry = no smart money interest
    if getattr(tech, "volume_dry", False):
        return "Volume dry (< 0.5x avg) — no institutional interest"

    return None  # All clear


# ─────────────────────────────────────────────────────────────
#  Main signal generator
# ─────────────────────────────────────────────────────────────

def generate_signal(result: ImpactResult) -> Optional[TradeSignal]:
    """
    Generate a trade signal for a given impact result.
    Returns None if no clear edge exists, or a NO TRADE signal
    if the setup is explicitly rejected.
    """
    pd = result.price_data
    if pd is None or pd.current_price <= 0:
        return None   # Never signal without confirmed price data

    price  = pd.current_price
    actual = result.actual_move_pct
    vol_r  = result.volume_ratio
    impact = result.impact_strength
    sent   = result.sentiment_label
    react  = result.reaction_status
    exp    = result.expected_move_pct

    # ── Determine action direction ────────────────────────────
    if sent == "Positive":
        direction = "BUY"
    elif sent == "Negative":
        direction = "SHORT"
    else:
        return None  # Neutral → no edge

    # ── Strict Filter Gate ────────────────────────────────────
    reject_reason = _strict_filter(result)
    if reject_reason:
        logger.info("NO TRADE %s: %s", result.symbol, reject_reason)
        return TradeSignal(
            symbol=result.symbol,
            name=result.name,
            action="NO TRADE",
            entry_low=0.0,
            entry_high=0.0,
            stop_loss=0.0,
            target1=0.0,
            target2=0.0,
            risk_reward=0.0,
            confidence=0,
            time_horizon="—",
            edge_type="—",
            rationale=f"NO TRADE: {reject_reason}",
        )

    # ── Compute buffer so stop/target give achievable R:R ────────
    # Prefer ATR from technicals; fall back to expected_move/4 so R:R ≥ 2
    _tech_buf = result.price_data.technical if result.price_data else None
    _atr_pct  = getattr(_tech_buf, "atr_pct", 0.0) if _tech_buf else 0.0
    if _atr_pct and 0.2 <= _atr_pct <= 4.0:
        buffer_pct = max(0.25, min(1.2, _atr_pct * 0.4))   # 40 % of daily ATR
    elif abs(exp) > 0:
        buffer_pct = max(0.25, min(1.2, abs(exp) / 4.0))   # stop = half expected move → R:R ≥ 2
    else:
        range_52w  = pd.high_52w - pd.low_52w
        buffer_pct = max(0.25, min(1.2, range_52w / max(pd.high_52w, 1) * 4))
    buffer = price * buffer_pct / 100

    # ── Entry zone ────────────────────────────────────────────
    if direction == "BUY":
        entry_low  = round(price, 2)
        entry_high = round(price + buffer, 2)
        stop_loss  = round(price - buffer * 2, 2)
        target1    = round(price * (1 + abs(exp) / 100 * 0.6), 2)
        target2    = round(price * (1 + abs(exp) / 100), 2)
    else:  # SHORT
        entry_high = round(price, 2)
        entry_low  = round(price - buffer, 2)
        stop_loss  = round(price + buffer * 2, 2)
        target1    = round(price * (1 - abs(exp) / 100 * 0.6), 2)
        target2    = round(price * (1 - abs(exp) / 100), 2)

    # ── Risk-Reward ───────────────────────────────────────────
    risk   = abs(price - stop_loss)
    reward = abs(target2 - price)
    rr     = round(reward / risk, 2) if risk > 0 else 0

    if rr < RISK_REWARD_MIN:
        return None   # Insufficient R:R

    # ── Confidence Score ──────────────────────────────────────
    confidence = _confidence_score(result, rr, vol_r, react)
    if confidence < CONFIDENCE_FLOOR:
        logger.info("Signal rejected %s: confidence %d < floor %d",
                     result.symbol, confidence, CONFIDENCE_FLOOR)
        return None

    # ── Time Horizon ──────────────────────────────────────────
    horizon = _time_horizon(result)

    # ── Edge Type ─────────────────────────────────────────────
    edge = "Underreaction" if react == "Underreacted" else (
        "Mean-Reversion"  if react == "Overreacted"  else
        "Macro"           if result.relation == "Macro" else
        "Momentum"
    )

    rationale = _build_rationale(result, rr, confidence, horizon, edge)

    return TradeSignal(
        symbol=result.symbol,
        name=result.name,
        action=direction if react != "Overreacted" else "AVOID",
        entry_low=entry_low,
        entry_high=entry_high,
        stop_loss=stop_loss,
        target1=target1,
        target2=target2,
        risk_reward=rr,
        confidence=confidence,
        time_horizon=horizon,
        edge_type=edge,
        rationale=rationale,
    )


# ─────────────────────────────────────────────────────────────
#  Confidence Scoring
# ─────────────────────────────────────────────────────────────

def _confidence_score(
    result: ImpactResult,
    rr: float,
    vol_ratio: float,
    reaction: str,
) -> int:
    score = 0
    direction = "BUY" if result.sentiment_label == "Positive" else "SHORT"

    # Impact strength (0–30 pts)
    score += {"EXTREME": 30, "HIGH": 22, "MEDIUM": 14, "LOW": 6}.get(result.impact_strength, 0)

    # Sentiment alignment (0–15 pts)
    score += {"Positive": 15, "Negative": 15, "Neutral": 0}.get(result.sentiment_label, 0)

    # Underreaction bonus (0–20 pts)
    if reaction == "Underreacted":
        score += 20
    elif reaction == "Reacted":
        score += 8

    # R:R quality (0–15 pts)
    if rr >= 3.0:
        score += 15
    elif rr >= 2.0:
        score += 10
    elif rr >= 1.5:
        score += 5

    # Volume confirmation (0–10 pts)
    if vol_ratio >= 2.0:
        score += 10
    elif vol_ratio >= 1.5:
        score += 5

    # Direct match boost (0–10 pts)
    if result.relation == "Direct":
        score += 10
    elif result.relation == "Sectoral":
        score += 4

    # ── News type penalty (Rumor = -10 pts) ─────────────────
    _news_type = getattr(result, "news_type", "Ongoing")
    if _news_type == "Rumor":
        score -= 10

    # ── Technical Analysis bonuses / penalties ────────────────
    tech = result.price_data.technical if result.price_data else None
    if tech:
        # RSI extremes — scaled by trend context to avoid "falling knife" false bonus
        # Oversold in uptrend = genuine reversal (+15). Oversold in downtrend = falling knife (0).
        if direction == "BUY" and tech.rsi_14 < 35:
            if tech.trend == "Uptrend":    score += 15  # strong reversal setup
            elif tech.trend == "Sideways": score += 8   # moderate bounce potential
            # Downtrend: 0 pts — falling knife, not a bounce
        elif direction == "SHORT" and tech.rsi_14 > 65:
            if tech.trend == "Downtrend":  score += 15  # strong continuation setup
            elif tech.trend == "Sideways": score += 8   # moderate
            # Uptrend: 0 pts — momentum stock, risky short

        # Near support/resistance (+10 pts)
        if direction == "BUY" and tech.near_support:
            score += 10
        elif direction == "SHORT" and tech.near_resistance:
            score += 10

        # Trend confirms direction (+8 pts / -6 pts)
        if (direction == "BUY"   and tech.trend == "Uptrend") or \
           (direction == "SHORT" and tech.trend == "Downtrend"):
            score += 8
        elif (direction == "BUY"   and tech.trend == "Downtrend") or \
             (direction == "SHORT" and tech.trend == "Uptrend"):
            score -= 6

        # Bollinger Band squeeze — breakout imminent (+5 pts)
        if tech.bb_squeeze:
            score += 5

        # MACD confirmation (+10 pts alignment, -5 pts contradiction)
        _macd_line = getattr(tech, "macd_line", 0.0)
        _macd_bull = getattr(tech, "macd_bullish", False)
        if _macd_line != 0.0:
            if direction == "BUY"   and _macd_bull:       score += 10
            elif direction == "BUY"   and not _macd_bull: score -= 5
            elif direction == "SHORT" and not _macd_bull: score += 10
            elif direction == "SHORT" and _macd_bull:     score -= 5

        # Stochastic extremes (+8 pts)
        if direction == "BUY"   and getattr(tech, "stoch_oversold",  False): score += 8
        elif direction == "SHORT" and getattr(tech, "stoch_overbought", False): score += 8

        # OBV trend alignment (+5 pts)
        _obv = getattr(tech, "obv_trend", "Neutral")
        if direction == "BUY"   and _obv == "Rising":  score += 5
        elif direction == "SHORT" and _obv == "Falling": score += 5

        # EMA(9) price position (+5 pts alignment, -3 pts contradiction)
        _ema9 = getattr(tech, "ema_9", 0.0)
        _above = getattr(tech, "price_above_ema9", False)
        if _ema9 != 0.0:
            if direction == "BUY"   and _above:      score += 5
            elif direction == "BUY"   and not _above: score -= 3
            elif direction == "SHORT" and not _above: score += 5
            elif direction == "SHORT" and _above:     score -= 3

        # ADX trend strength (direction-agnostic — avoids double-scoring)
        _adx_val = getattr(tech, "adx_14", 0.0)
        _adx_trending = getattr(tech, "adx_trending", False)
        if _adx_trending:
            score += 5   # strong trend bonus
        elif _adx_val > 0:
            score -= 3   # weak/choppy trend penalty

        # SuperTrend (+12 aligned, -7 contradiction)
        _st = getattr(tech, "supertrend_bullish", None)
        if _st is not None:
            if direction == "BUY"   and _st:       score += 12
            elif direction == "BUY"   and not _st: score -= 7
            elif direction == "SHORT" and not _st: score += 12
            elif direction == "SHORT" and _st:     score -= 7

        # CCI extremes (+8 pts)
        if direction == "BUY"   and getattr(tech, "cci_oversold",   False): score += 8
        elif direction == "SHORT" and getattr(tech, "cci_overbought", False): score += 8

        # VWAP alignment (+5 pts)
        _vwap = getattr(tech, "vwap_5d", 0.0)
        if _vwap > 0:
            _above_vwap = getattr(tech, "price_above_vwap", False)
            if direction == "BUY"   and _above_vwap:     score += 5
            elif direction == "SHORT" and not _above_vwap: score += 5

        # Volume spike aligned with direction (+8 pts)
        if getattr(tech, "volume_spike", False):
            score += 8

        # Pre-breakout accumulation (+10 pts)
        if getattr(tech, "pre_breakout", False):
            score += 10

        # Market regime penalty
        _regime = getattr(tech, "market_regime", "Unknown")
        if _regime == "HighVol":
            score -= 10

    return max(0, min(score, 100))


# ─────────────────────────────────────────────────────────────
#  Time Horizon
# ─────────────────────────────────────────────────────────────

def _time_horizon(result: ImpactResult) -> str:
    _news_type = getattr(result, "news_type", "Ongoing")
    if _news_type == "Breaking":
        return "Intraday"
    if result.impact_strength in ("EXTREME", "HIGH"):
        return "Intraday / Short-term"
    if result.reaction_status == "Underreacted":
        return "Short-term (2–5 days)"
    if result.relation in ("Sectoral", "Macro"):
        return "Swing (1–3 weeks)"
    return "Short-term (3–7 days)"


# ─────────────────────────────────────────────────────────────
#  Rationale Builder
# ─────────────────────────────────────────────────────────────

def _build_rationale(result, rr, conf, horizon, edge) -> str:
    parts = []
    parts.append(f"{result.impact_strength} impact {result.sentiment_label.lower()} news ({result.relation})")
    parts.append(f"expected {result.expected_move_pct:+.1f}% vs actual {result.actual_move_pct:+.1f}%")
    parts.append(f"vol ratio {result.volume_ratio:.1f}x")
    parts.append(f"R:R {rr:.1f}")
    parts.append(f"edge: {edge}")
    tech = result.price_data.technical if result.price_data else None
    if tech:
        parts.append(f"RSI {tech.rsi_14:.0f} ({tech.trend})")
        regime = getattr(tech, "market_regime", "Unknown")
        if regime != "Unknown":
            parts.append(f"regime: {regime}")
        if tech.near_support:
            parts.append("near support")
        if tech.near_resistance:
            parts.append("near resistance")
        if tech.bb_squeeze:
            parts.append("BB squeeze")
        if getattr(tech, "macd_bullish", None) is not None and tech.macd_line != 0.0:
            parts.append("MACD " + ("bullish" if tech.macd_bullish else "bearish"))
        if getattr(tech, "stoch_oversold", False):
            parts.append(f"Stoch {tech.stoch_k:.0f} oversold")
        elif getattr(tech, "stoch_overbought", False):
            parts.append(f"Stoch {tech.stoch_k:.0f} overbought")
        obv = getattr(tech, "obv_trend", "Neutral")
        if obv in ("Rising", "Falling"):
            parts.append(f"OBV {obv.lower()}")
        atr_pct = getattr(tech, "atr_pct", 0.0)
        if atr_pct > 2.0:
            parts.append(f"ATR {atr_pct:.1f}% vol")
        adx_v = getattr(tech, "adx_14", 0.0)
        if adx_v > 0:
            parts.append(f"ADX {adx_v:.0f}{'★' if adx_v > 25 else ''}")
        st = getattr(tech, "supertrend_bullish", None)
        if st is not None:
            parts.append("ST " + ("bullish" if st else "bearish"))
        cci_v = getattr(tech, "cci_20", 0.0)
        if getattr(tech, "cci_oversold", False):
            parts.append(f"CCI {cci_v:.0f} oversold")
        elif getattr(tech, "cci_overbought", False):
            parts.append(f"CCI {cci_v:.0f} overbought")
        vwap = getattr(tech, "vwap_5d", 0.0)
        if vwap > 0:
            parts.append("VWAP " + ("above" if getattr(tech, "price_above_vwap", False) else "below"))
        if getattr(tech, "volume_spike", False):
            parts.append("VOL SPIKE")
        if getattr(tech, "pre_breakout", False):
            parts.append("PRE-BREAKOUT")
    return " | ".join(parts)
