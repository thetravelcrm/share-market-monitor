#!/usr/bin/env python3
"""
silvermic_monitor.py — headless SILVERMIC monitor for GitHub Actions (cron).

3-gate "perfect entry" pipeline, runs without a browser open:
    market open (holiday-aware) → Fyers auto-login (TOTP) → SILVERMIC signal
    → GATE 1+2: technical LONG AND silver news CONFIRMED
    → GATE 3: DeepSeek pro + thinking final confirmation (CONFIRM, high conviction)
    → Slack "PERFECT ENTRY" alert.

Config via ENVIRONMENT VARIABLES (GitHub repo Secrets):
    FYERS_CLIENT_ID, FYERS_SECRET_KEY, FYERS_ID, FYERS_TOTP_SECRET, FYERS_PIN
    SM_RSI_ENTRY_MIN, SM_EMA_SPREAD_MIN, SM_RSI_BULL_LEVEL   (match the app)
    DEEPSEEK_API_KEY (+ optional DEEPSEEK_MODEL / DEEPSEEK_THINKING)
    SLACK_BOT_TOKEN, SLACK_CHANNEL
    GIST_TOKEN + MONITOR_STATE_GIST   (dedup state, shared with the app)

Dedup: the "PERFECT" alert fires once per setup/day via the shared gist state
(monitor_state), so the app and cron never double-send.

Exit code is 0 on every clean run (including "market closed" / "not a setup");
only unexpected errors return non-zero.
"""
from __future__ import annotations

import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [monitor] %(levelname)s: %(message)s")
log = logging.getLogger("silvermic_monitor")


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return float(default)


def main() -> int:
    # 1. Market open? (holiday- and session-aware; e.g. Moharram morning closed)
    from mcx_calendar import is_market_open, session_label, ist_now
    ist = ist_now()
    if not is_market_open(ist):
        log.info("MCX closed (%s, %s IST) — nothing to do",
                 session_label(ist), ist.strftime("%a %H:%M"))
        return 0
    today = ist.strftime("%Y-%m-%d")

    # 2. Fyers auto-login (TOTP) — credentials from env
    from fyers_fetcher import auto_login, is_auto_login_configured
    if not is_auto_login_configured():
        log.error("Fyers auto-login not configured — set FYERS_* secrets")
        return 1
    token, err = auto_login()
    if not token:
        log.error("Fyers auto-login failed: %s", err)
        return 1
    log.info("Fyers connected")

    # 3. SILVERMIC signal — same tuned thresholds as the app
    from silvermic_strategy import analyze
    try:
        res = analyze(
            token,
            rsi_entry_min=_f("SM_RSI_ENTRY_MIN", 52.0),
            ema_spread_min=_f("SM_EMA_SPREAD_MIN", 0.09),
            rsi_bull_min=_f("SM_RSI_BULL_LEVEL", 50.0),
        )
    except Exception as exc:
        log.error("SILVERMIC analyze failed: %s", exc)
        return 1

    sig  = res.signal
    news = res.news_verdict or {}
    news_decision = news.get("decision")
    log.info("signal=%s  news=%s (%s)", sig, news_decision, news.get("label"))

    import monitor_state

    # ── GATE 1 + 2: technical LONG AND news CONFIRMED ──
    if sig != "LONG" or news_decision != "CONFIRMED":
        log.info("Not a perfect setup (need LONG + news CONFIRMED) — no alert")
        monitor_state.reset(today)        # clear marker so the next real setup alerts
        return 0

    if monitor_state.already_alerted(today, "PERFECT"):
        log.info("PERFECT entry already alerted today — skipping")
        return 0

    # ── GATE 3: DeepSeek pro + thinking final confirmation ──
    facts = {"signal": sig, "htf": res.htf, "entry": res.entry, "news_verdict": news}
    deep_note = "Technical + News confirmed (AI gate unavailable)"
    try:
        import deepseek_analyzer as dsa
        if dsa.is_configured():
            verdict = dsa.confirm_silvermic_entry(facts)   # pro + thinking
            log.info("DeepSeek(pro) verdict=%s conf=%s%% reasons=%s",
                     verdict.verdict, verdict.confidence, verdict.reasons[:2])
            if not dsa.is_perfect_entry(verdict):
                log.info("DeepSeek did not CONFIRM a perfect entry — no alert")
                return 0   # leave marker unset so it re-checks next run
            deep_note = (f"AI CONFIRM {verdict.confidence}% — "
                         + (verdict.reasons[0] if verdict.reasons else "clean setup"))
        else:
            log.warning("DeepSeek not configured — alerting on tech+news only")
    except Exception as exc:
        log.warning("DeepSeek gate failed (%s) — alerting on tech+news only", exc)

    # ── Slack "PERFECT ENTRY" ──
    bot  = os.environ.get("SLACK_BOT_TOKEN", "")
    chan = os.environ.get("SLACK_CHANNEL", "#general")
    if not bot:
        log.error("SLACK_BOT_TOKEN missing — cannot alert")
        return 1
    from notifier import send_slack_alert
    ent = res.entry or {}
    ep  = ent.get("entry_price", 0)
    ins = news.get("top_insights", [])
    ok = send_slack_alert(bot, chan, {
        "header":        "🎯 PERFECT ENTRY — SILVERMIC LONG",
        "entry":         ep,
        "stop_loss":     ent.get("stop_loss", 0),
        "t1":            round(ep + 1500, 0),
        "t2":            round(ep + 4000, 0),
        "t3":            round(ep + 11000, 0),
        "news_score":    news.get("score", "N/A"),
        "news_label":    news.get("label", "N/A"),
        "news_decision": deep_note,
        "top_insight":   ins[0] if ins else "Technical + News + AI all CONFIRMED",
    })
    if ok:
        log.info("PERFECT ENTRY Slack alert sent")
        monitor_state.mark_alerted(today, "PERFECT")
    else:
        log.error("Slack send failed")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log.exception("monitor crashed: %s", exc)
        sys.exit(1)
