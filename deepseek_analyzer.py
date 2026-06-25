# ─────────────────────────────────────────────────────────────
#  deepseek_analyzer.py  –  Real-time AI reality-check on signals
#
#  Uses DeepSeek's Anthropic-compatible API:
#      base_url : https://api.deepseek.com/anthropic
#      endpoint : POST {base_url}/v1/messages   (Anthropic Messages format)
#      auth     : x-api-key header  (fully supported per DeepSeek docs)
#      models   : deepseek-v4-pro (deep) | deepseek-v4-flash (fast, default)
#
#  Config (Streamlit Cloud → Settings → Secrets, or env vars):
#      DEEPSEEK_API_KEY  = "sk-..."             # REQUIRED
#      DEEPSEEK_MODEL    = "deepseek-v4-pro"    # optional; default deepseek-v4-pro
#      DEEPSEEK_THINKING = "on"                 # optional; reasoning mode (default on)
#
#  GROUNDING RULE: every function feeds the model ONLY the numbers this app
#  already computed. The system prompt forbids inventing prices/news. This is
#  a second-opinion risk filter, NOT a source of new facts.
#  Nothing here is financial advice.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL  = "https://api.deepseek.com/anthropic"
_ENDPOINT  = f"{_BASE_URL}/v1/messages"
_DEFAULT_MODEL  = "deepseek-v4-pro"   # deep reasoning model; override via DEEPSEEK_MODEL
_TIMEOUT_FAST   = 45       # seconds — non-thinking calls
_TIMEOUT_THINK  = 120      # seconds — reasoning/thinking calls run notably longer
_THINK_HEADROOM = 1600     # extra max_tokens so reasoning doesn't starve the final answer

# In-process cache so Streamlit reruns / repeat clicks don't re-bill identical calls.
_cache: dict[str, "AIVerdict"] = {}


@dataclass
class AIVerdict:
    verdict:    str          # "CONFIRM" | "CAUTION" | "AVOID" | "INFO" | "ERROR"
    confidence: int          # 0–100  (model's own conviction in its verdict)
    reasons:    list[str]    # short bullet reasons, grounded in the supplied data
    raw:        str          # full model text (for display / debugging)
    ok:         bool = True  # False when the call failed or wasn't configured


# ─────────────────────────────────────────────────────────────
#  Secrets / config
# ─────────────────────────────────────────────────────────────

def _get_secret(name: str, default: str = "") -> str:
    """Read from Streamlit secrets first, then environment. Never raises."""
    try:
        import streamlit as st
        val = st.secrets.get(name, "")
        if val:
            return str(val)
    except Exception:
        pass
    return os.environ.get(name, default)


def get_api_key() -> str:
    return _get_secret("DEEPSEEK_API_KEY", "")


def get_model() -> str:
    return _get_secret("DEEPSEEK_MODEL", _DEFAULT_MODEL) or _DEFAULT_MODEL


def is_configured() -> bool:
    """True only when a DeepSeek API key is present. UI gates on this."""
    return bool(get_api_key())


def _thinking_enabled() -> bool:
    """
    Reasoning/thinking mode. ON by default (best analysis quality) — set
    DEEPSEEK_THINKING = "off" in secrets to disable it for lower cost/latency.
    """
    val = _get_secret("DEEPSEEK_THINKING", "on").strip().lower()
    return val not in ("0", "off", "false", "no")


# ─────────────────────────────────────────────────────────────
#  Low-level call
# ─────────────────────────────────────────────────────────────

def _call(system: str, user: str, max_tokens: int = 500,
          temperature: float = 0.2) -> tuple[bool, str]:
    """
    POST one message to DeepSeek's Anthropic-compatible endpoint.
    Returns (ok, text). Never raises — failures come back as (False, reason).
    """
    key = get_api_key()
    if not key:
        return False, "DeepSeek API key not configured (set DEEPSEEK_API_KEY in secrets)."

    think = _thinking_enabled()
    headers = {
        "x-api-key":         key,        # DeepSeek: fully supported
        "anthropic-version": "2023-06-01",  # ignored by DeepSeek but harmless
        "content-type":      "application/json",
    }
    payload = {
        "model":      get_model(),
        # Leave headroom in thinking mode so reasoning tokens don't starve the answer.
        "max_tokens": (max_tokens + _THINK_HEADROOM) if think else max_tokens,
        "system":     system,
        "messages":   [{"role": "user", "content": user}],
    }
    if think:
        # DeepSeek's Anthropic-compatible endpoint accepts the Anthropic `thinking`
        # field ('budget_tokens' is ignored by DeepSeek). A custom temperature is
        # disallowed while thinking is on, so it is omitted. The reasoning comes back
        # as non-text content blocks, which _parse_verdict / the parser skip.
        payload["thinking"] = {"type": "enabled", "budget_tokens": 2048}
    else:
        payload["temperature"] = temperature
    try:
        resp = requests.post(_ENDPOINT, headers=headers, data=json.dumps(payload),
                             timeout=_TIMEOUT_THINK if think else _TIMEOUT_FAST)
    except requests.exceptions.Timeout:
        return False, "DeepSeek request timed out — try again (thinking mode is slower)."
    except Exception as exc:
        return False, f"DeepSeek network error: {exc}"

    if resp.status_code != 200:
        # Surface the API's own error message but keep it short.
        try:
            err = resp.json()
            msg = err.get("error", {}).get("message") or err.get("message") or resp.text[:300]
        except Exception:
            msg = resp.text[:300]
        logger.warning("DeepSeek API %s: %s", resp.status_code, msg)
        return False, f"DeepSeek API error {resp.status_code}: {msg}"

    try:
        data = resp.json()
        # Anthropic Messages response: {"content": [{"type":"text","text": "..."}], ...}
        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        if not text:
            return False, "DeepSeek returned an empty response."
        return True, text
    except Exception as exc:
        return False, f"Could not parse DeepSeek response: {exc}"


# ─────────────────────────────────────────────────────────────
#  Response parsing  (VERDICT / CONFIDENCE / bullet reasons)
# ─────────────────────────────────────────────────────────────

_VALID_VERDICTS = {"CONFIRM", "CAUTION", "AVOID", "INFO"}


def _parse_verdict(text: str, default_verdict: str = "INFO") -> AIVerdict:
    verdict = default_verdict
    confidence = 0
    reasons: list[str] = []

    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        up = s.upper()
        if up.startswith("VERDICT:"):
            v = up.split(":", 1)[1].strip().split()[0] if ":" in up else ""
            if v in _VALID_VERDICTS:
                verdict = v
        elif up.startswith("AI_CONFIDENCE:") or up.startswith("CONFIDENCE:"):
            digits = "".join(c for c in s.split(":", 1)[1] if c.isdigit())
            if digits:
                confidence = max(0, min(100, int(digits)))
        elif s[0] in "-•*" or (len(s) > 2 and s[0].isdigit() and s[1] in ").:"):
            reasons.append(s.lstrip("-•*0123456789).: ").strip())

    return AIVerdict(verdict=verdict, confidence=confidence, reasons=reasons, raw=text, ok=True)


# ─────────────────────────────────────────────────────────────
#  Grounded data serialisers — feed the model ONLY known numbers
# ─────────────────────────────────────────────────────────────

def _signal_facts(sig, imp) -> str:
    """Compact, factual description of a signal + its impact result."""
    pd_  = getattr(imp, "price_data", None)
    tech = getattr(pd_, "technical", None) if pd_ else None
    cur  = "$" if (pd_ and getattr(pd_, "currency", "INR") == "USD") else "₹"

    lines = [
        f"SYMBOL: {imp.symbol} ({imp.name}) | sector: {imp.sector}",
        f"PROPOSED ACTION: {sig.action}  (system confidence {sig.confidence}/100, edge: {sig.edge_type})",
        f"ENTRY: {cur}{sig.entry_low}–{cur}{sig.entry_high} | STOP: {cur}{sig.stop_loss} "
        f"| T1: {cur}{sig.target1} | T2: {cur}{sig.target2} | R:R {sig.risk_reward} | horizon {sig.time_horizon}",
        f"NEWS RELATION: {imp.relation} | impact_strength: {imp.impact_strength} "
        f"| news_type: {imp.news_type} | match_reason: {getattr(imp, 'match_reason', '') or 'n/a'}",
        f"MOVE: expected {imp.expected_move_pct:+.1f}% vs actual {imp.actual_move_pct:+.1f}% today "
        f"| volume {imp.volume_ratio:.1f}x average | reaction: {imp.reaction_status}",
    ]
    if pd_:
        lines.append(
            f"PRICE: {cur}{pd_.current_price} | day change {pd_.day_change_pct:+.2f}% "
            f"| 52w {cur}{pd_.low_52w}–{cur}{pd_.high_52w}"
        )
    if tech:
        lines.append(
            f"TECH: trend {tech.trend} | regime {getattr(tech,'market_regime','?')} "
            f"| RSI {tech.rsi_14:.0f} | Stoch %K {getattr(tech,'stoch_k',0):.0f} "
            f"| MACD {'bull' if getattr(tech,'macd_bullish',False) else 'bear'} "
            f"| ADX {getattr(tech,'adx_14',0):.0f} | ATR {getattr(tech,'atr_pct',0):.1f}% "
            f"| near_support={tech.near_support} near_resistance={tech.near_resistance} "
            f"| SuperTrend={'bull' if getattr(tech,'supertrend_bullish',None) else 'bear/na'}"
        )
    return "\n".join(lines)


_SIGNAL_SYSTEM = (
    "You are a disciplined Indian equity & MCX trading risk reviewer. "
    "Use ONLY the structured data given to you. NEVER invent prices, news, indicator "
    "values, or numbers that are not provided; if data is missing, say so. "
    "Your single job: decide whether the stated facts genuinely justify the PROPOSED ACTION, "
    "or whether it is a low-quality / chase setup. Be skeptical and specifically check for: "
    "(1) news that merely lists or mentions the stock — e.g. 'top gainers/losers', 'movers', "
    "'stocks to watch' recaps — rather than a real, specific catalyst; "
    "(2) overbought RSI (>70) or Stochastic (>80) on a fresh BUY (or oversold on a fresh SHORT) — chasing; "
    "(3) price near resistance for a BUY, or near support for a SHORT — poor location; "
    "(4) below-average volume (<1x) — no institutional confirmation; "
    "(5) the move already played out (actual move ≈ or > expected) — edge gone; "
    "(6) high-volatility regime inflating risk. "
    "Reward only setups where a concrete catalyst aligns with price/volume/trend. "
    "Respond in EXACTLY this format and nothing else:\n"
    "VERDICT: CONFIRM|CAUTION|AVOID\n"
    "AI_CONFIDENCE: <integer 0-100>\n"
    "- <reason 1, citing the specific data point>\n"
    "- <reason 2>\n"
    "- <reason 3 (optional)>\n"
    "Use CONFIRM only when the catalyst is real and price/volume/trend agree; "
    "CAUTION when mixed; AVOID when the action is unjustified by the data."
)


def analyze_signal(sig, imp, use_cache: bool = True) -> AIVerdict:
    """Real-time AI reality-check on a single trade signal. Grounded; never raises."""
    if not is_configured():
        return AIVerdict("ERROR", 0, [], "DeepSeek not configured.", ok=False)

    facts = _signal_facts(sig, imp)
    ckey = "sig:" + str(hash(facts))
    if use_cache and ckey in _cache:
        return _cache[ckey]

    user = (
        "Review this trade setup and judge whether the PROPOSED ACTION is justified "
        "by the data:\n\n" + facts
    )
    ok, text = _call(_SIGNAL_SYSTEM, user, max_tokens=400)
    if not ok:
        return AIVerdict("ERROR", 0, [], text, ok=False)

    verdict = _parse_verdict(text, default_verdict="CAUTION")
    if use_cache:
        _cache[ckey] = verdict
    return verdict


# ─────────────────────────────────────────────────────────────
#  Top-level market brief
# ─────────────────────────────────────────────────────────────

_BRIEF_SYSTEM = (
    "You are a concise Indian market desk analyst. Use ONLY the data provided — "
    "do not invent stocks, prices, or events. Summarise the current picture for a "
    "trader in 4-6 short bullets: overall tone, the 1-2 strongest genuinely-actionable "
    "setups (and why), anything that looks like noise/chasing to ignore, and key risks. "
    "Plain text bullets only. End with one line: 'Not financial advice.'"
)


def market_brief(signals_facts: list[str], extra_context: str = "",
                 use_cache: bool = True) -> AIVerdict:
    """
    Build a top-level AI brief from a list of pre-serialised signal fact strings
    (use facts_for_brief() to build them) plus optional market context.
    """
    if not is_configured():
        return AIVerdict("ERROR", 0, [], "DeepSeek not configured.", ok=False)
    if not signals_facts and not extra_context:
        return AIVerdict("INFO", 0, ["No signals to analyse."], "", ok=True)

    body = "\n\n".join(signals_facts[:12])
    if extra_context:
        body = extra_context.strip() + "\n\n" + body

    ckey = "brief:" + str(hash(body))
    if use_cache and ckey in _cache:
        return _cache[ckey]

    ok, text = _call(_BRIEF_SYSTEM,
                     "Here is the current scan output:\n\n" + body,
                     max_tokens=600)
    if not ok:
        return AIVerdict("ERROR", 0, [], text, ok=False)
    verdict = _parse_verdict(text, default_verdict="INFO")
    if use_cache:
        _cache[ckey] = verdict
    return verdict


def facts_for_brief(sig, imp) -> str:
    """One-line fact string for market_brief()."""
    return _signal_facts(sig, imp)


# ─────────────────────────────────────────────────────────────
#  SILVERMIC live-signal verdict
# ─────────────────────────────────────────────────────────────

_SILVER_SYSTEM = (
    "You are a disciplined MCX silver (SILVERMIC) intraday risk reviewer. Use ONLY the "
    "data provided; never invent prices or news. The technical strategy is long-only "
    "(VWAP + EMA9/21 + SuperTrend MTF + RSI). Judge whether going LONG now is justified, "
    "weighing the technical signal against the silver news sentiment. Flag traps where "
    "technicals say LONG but news is bearish, or where conditions are barely met. "
    "Respond EXACTLY:\n"
    "VERDICT: CONFIRM|CAUTION|AVOID\n"
    "AI_CONFIDENCE: <integer 0-100>\n"
    "- <reason citing a specific data point>\n"
    "- <reason>\n"
)


def analyze_silvermic(sm: dict, use_cache: bool = True) -> AIVerdict:
    """
    AI verdict on the SILVERMIC live signal.
    `sm` is a plain dict of facts (signal, htf, entry, news_verdict) — caller builds it.
    """
    if not is_configured():
        return AIVerdict("ERROR", 0, [], "DeepSeek not configured.", ok=False)

    facts = json.dumps(sm, default=str, indent=2)
    ckey = "silver:" + str(hash(facts))
    if use_cache and ckey in _cache:
        return _cache[ckey]

    ok, text = _call(_SILVER_SYSTEM,
                     "Current SILVERMIC state:\n\n" + facts, max_tokens=400)
    if not ok:
        return AIVerdict("ERROR", 0, [], text, ok=False)
    verdict = _parse_verdict(text, default_verdict="CAUTION")
    if use_cache:
        _cache[ckey] = verdict
    return verdict
