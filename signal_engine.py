# ─────────────────────────────────────────────────────────────
#  signal_engine.py  –  Generate BUY / SELL / SHORT signals
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config import RISK_REWARD_MIN, CONFIDENCE_FLOOR
from impact_analyzer import ImpactResult, PriceData


@dataclass
class TradeSignal:
    symbol: str
    name: str
    action: str              # BUY | SELL | SHORT | AVOID
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


def generate_signal(result: ImpactResult) -> Optional[TradeSignal]:
    """
    Generate a trade signal for a given impact result.
    Returns None if no clear edge exists.
    """
    pd = result.price_data
    if pd is None or pd.current_price <= 0:
        return _no_price_signal(result)

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

    # ── Compute ATR-like buffer from 52w range ─────────────────
    range_52w  = pd.high_52w - pd.low_52w
    buffer_pct = max(0.5, min(2.5, range_52w / pd.high_52w * 10))
    buffer     = price * buffer_pct / 100

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
        entry_low=entry_low if direction == "BUY" else entry_low,
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

    # ── Technical Analysis bonuses / penalties ────────────────
    tech = result.price_data.technical if result.price_data else None
    if tech:
        # Oversold RSI on BUY — strong entry confirmation (+15 pts)
        if direction == "BUY" and tech.rsi_14 < 35:
            score += 15
        # Overbought RSI on SHORT — strong entry confirmation (+15 pts)
        elif direction == "SHORT" and tech.rsi_14 > 65:
            score += 15

        # Near support on BUY (+10 pts)
        if direction == "BUY" and tech.near_support:
            score += 10
        # Near resistance on SHORT (+10 pts)
        elif direction == "SHORT" and tech.near_resistance:
            score += 10

        # Trend confirms direction (+8 pts)
        if (direction == "BUY"   and tech.trend == "Uptrend") or \
           (direction == "SHORT" and tech.trend == "Downtrend"):
            score += 8
        # Trend opposes direction — penalty (-10 pts)
        elif (direction == "BUY"   and tech.trend == "Downtrend") or \
             (direction == "SHORT" and tech.trend == "Uptrend"):
            score -= 10

        # Bollinger Band squeeze — breakout imminent (+5 pts)
        if tech.bb_squeeze:
            score += 5

        # MACD confirmation (+10 pts)
        if direction == "BUY"   and getattr(tech, "macd_bullish", False):
            score += 10
        elif direction == "SHORT" and not getattr(tech, "macd_bullish", True):
            score += 10

        # Stochastic extremes (+8 pts)
        if direction == "BUY"   and getattr(tech, "stoch_oversold", False):
            score += 8
        elif direction == "SHORT" and getattr(tech, "stoch_overbought", False):
            score += 8

        # OBV trend alignment (+5 pts)
        if direction == "BUY"   and getattr(tech, "obv_trend", "") == "Rising":
            score += 5
        elif direction == "SHORT" and getattr(tech, "obv_trend", "") == "Falling":
            score += 5

        # EMA(9) price position (+5 pts)
        if direction == "BUY"   and getattr(tech, "price_above_ema9", False):
            score += 5
        elif direction == "SHORT" and not getattr(tech, "price_above_ema9", True):
            score += 5

    return max(0, min(score, 100))


def _time_horizon(result: ImpactResult) -> str:
    if result.impact_strength in ("EXTREME", "HIGH"):
        return "Intraday / Short-term"
    if result.reaction_status == "Underreacted":
        return "Short-term (2–5 days)"
    if result.relation in ("Sectoral", "Macro"):
        return "Swing (1–3 weeks)"
    return "Short-term (3–7 days)"


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
        if tech.near_support:
            parts.append("near support ✓")
        if tech.near_resistance:
            parts.append("near resistance ✓")
        if tech.bb_squeeze:
            parts.append("BB squeeze ⚡")
        if getattr(tech, "macd_bullish", None) is not None and tech.macd_line != 0.0:
            parts.append("MACD ↑ bullish" if tech.macd_bullish else "MACD ↓ bearish")
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
    return " | ".join(parts)


def _no_price_signal(result: ImpactResult) -> Optional[TradeSignal]:
    """Fallback signal when live price is unavailable."""
    if result.impact_strength not in ("HIGH", "EXTREME"):
        return None
    if result.sentiment_label == "Neutral":
        return None

    direction = "BUY" if result.sentiment_label == "Positive" else "SHORT"
    return TradeSignal(
        symbol=result.symbol,
        name=result.name,
        action=direction,
        entry_low=0.0,
        entry_high=0.0,
        stop_loss=0.0,
        target1=0.0,
        target2=0.0,
        risk_reward=0.0,
        confidence=30,
        time_horizon="Short-term",
        edge_type="Macro",
        rationale=f"No live price – {direction} bias from {result.impact_strength} impact news",
    )
