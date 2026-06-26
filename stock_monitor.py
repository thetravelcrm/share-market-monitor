#!/usr/bin/env python3
"""
stock_monitor.py — headless news-driven STOCK perfect-entry monitor (GitHub cron).

Runs the full news pipeline without a browser and alerts only on bulletproof
3-gate setups:
    NSE open (holiday-aware) → run_pipeline (news → sentiment → map → prices →
    signals) → fast DeepSeek screen (drop AVOID) → DeepSeek pro+thinking final
    gate on the top high-confidence signals → Slack "PERFECT ENTRY".

Prices in the cron come from yfinance (no Streamlit Fyers session); the signal
logic, news gate and AI gates are identical to the app.

Config via ENVIRONMENT VARIABLES (GitHub repo Secrets / workflow env):
    DEEPSEEK_API_KEY (+ optional DEEPSEEK_MODEL / DEEPSEEK_THINKING)
    SLACK_BOT_TOKEN, SLACK_CHANNEL
    GIST_TOKEN + MONITOR_STATE_GIST            (dedup, shared with the app)
    STOCK_NEWS_HOURS (default 12), STOCK_TOP_N (default 20),
    PERFECT_MIN_CONF (default 80), PERFECT_MAX_CHECK (default 3)

Dedup: each symbol alerts at most once per day (shared gist state).
Exit code is 0 on every clean run; only unexpected errors return non-zero.
"""
from __future__ import annotations

import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [stock-monitor] %(levelname)s: %(message)s")
log = logging.getLogger("stock_monitor")


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return int(default)


def main() -> int:
    # 1. NSE open? (weekend + known-holiday aware)
    from mcx_calendar import is_nse_open, ist_now
    ist = ist_now()
    if not is_nse_open(ist):
        log.info("NSE closed (%s IST) — nothing to do", ist.strftime("%a %H:%M"))
        return 0
    today = ist.strftime("%Y-%m-%d")

    # 2. DeepSeek is mandatory for the bulletproof gate
    import deepseek_analyzer as dsa
    if not dsa.is_configured():
        log.warning("DeepSeek not configured — perfect-entry gate unavailable; exiting")
        return 0

    # 3. Run the full news → signal pipeline (yfinance prices in headless mode)
    from pipeline import run_pipeline
    try:
        res = run_pipeline(hours=_i("STOCK_NEWS_HOURS", 12),
                           top_n=_i("STOCK_TOP_N", 20), fetch_prices=True)
    except Exception as exc:
        log.error("pipeline failed: %s", exc)
        return 1

    signals = [(it, imp, sig) for it, imp, sig in res.all_signals
               if sig.action in ("BUY", "SHORT")]
    log.info("pipeline produced %d BUY/SHORT signals", len(signals))
    if not signals:
        return 0

    # 4. Fast screen — drop AVOID
    approved = []
    for it, imp, sig in signals:
        try:
            v = dsa.screen_signal(sig, imp)
        except Exception:
            v = None
        if v is None or not v.ok or v.verdict != "AVOID":
            approved.append((it, imp, sig))
    log.info("%d signals passed the fast screen", len(approved))

    # 5. Deep pro+thinking final gate on the top high-confidence candidates
    min_conf = _i("PERFECT_MIN_CONF", 80)
    cands = sorted([t for t in approved if getattr(t[2], "confidence", 0) >= min_conf],
                   key=lambda t: t[2].confidence, reverse=True)[:_i("PERFECT_MAX_CHECK", 3)]
    log.info("deep-gating %d candidate(s)", len(cands))

    bot  = os.environ.get("SLACK_BOT_TOKEN", "")
    chan = os.environ.get("SLACK_CHANNEL", "#general")
    import monitor_state
    from notifier import send_perfect_stock_alert

    sent = 0
    for it, imp, sig in cands:
        try:
            verdict = dsa.confirm_signal_entry(sig, imp)
        except Exception as exc:
            log.warning("deep gate failed for %s: %s", imp.symbol, exc)
            continue
        log.info("%s %s: %s %s%%", sig.action, imp.symbol, verdict.verdict, verdict.confidence)
        if not dsa.is_perfect_entry(verdict):
            continue
        if monitor_state.stock_already_alerted(imp.symbol, today):
            log.info("%s already alerted today — skipping", imp.symbol)
            continue
        cur = "$" if (imp.price_data and getattr(imp.price_data, "currency", "INR") == "USD") else "₹"
        if not bot:
            log.error("SLACK_BOT_TOKEN missing — cannot alert")
            continue
        ok = send_perfect_stock_alert(bot, chan, {
            "symbol": imp.symbol, "name": imp.name, "action": sig.action,
            "entry":  f"{cur}{sig.entry_low:,.2f}–{cur}{sig.entry_high:,.2f}",
            "stop":   f"{cur}{sig.stop_loss:,.2f}",
            "target": f"{cur}{sig.target2:,.2f}",
            "rr":     sig.risk_reward, "ai_conf": verdict.confidence,
            "reason": verdict.reasons[0] if verdict.reasons else "Clean high-probability setup",
        })
        if ok:
            monitor_state.mark_stock_alerted(imp.symbol, today)
            sent += 1

    log.info("PERFECT ENTRY stock alerts sent: %d", sent)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log.exception("stock_monitor crashed: %s", exc)
        sys.exit(1)
