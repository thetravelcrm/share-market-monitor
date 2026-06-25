#!/usr/bin/env python3
"""
silvermic_monitor.py — headless SILVERMIC monitor for GitHub Actions (cron).

Runs without Streamlit so it can alert even when no browser is open:
    Fyers auto-login (TOTP) → SILVERMIC signal → DeepSeek screen → Slack alert.

All config comes from ENVIRONMENT VARIABLES (set as GitHub repo Secrets):
    FYERS_CLIENT_ID, FYERS_SECRET_KEY, FYERS_ID, FYERS_TOTP_SECRET, FYERS_PIN
    DEEPSEEK_API_KEY            (optional — if absent, no AI gate; alert on LONG)
    DEEPSEEK_SCREEN_MODEL       (optional — default deepseek-v4-flash)
    SLACK_BOT_TOKEN             (xoxb-… bot token)
    SLACK_CHANNEL              (e.g. "#general" or a channel ID)
    GITHUB_TOKEN + MONITOR_STATE_GIST (or GIST_HISTORY_ID)  (optional — dedup state)

Dedup: a Slack alert fires only on a WAIT→LONG transition for the day. The
"last alerted" state is kept in a GitHub Gist; without it the alert may repeat
each run while LONG (keep the cron interval >= 15 min to limit this).

Exit code is always 0 on a clean run (including "market closed" / "not LONG")
so the workflow shows green; only unexpected errors return non-zero.
"""
from __future__ import annotations

import os
import sys
import json
import logging
from datetime import datetime, timezone, timedelta

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [monitor] %(levelname)s: %(message)s")
log = logging.getLogger("silvermic_monitor")

_STATE_FILE = "silvermic_monitor_state.json"


# ─────────────────────────────────────────────────────────────
#  Gist-backed dedup state (optional)
# ─────────────────────────────────────────────────────────────

def _gist_ids() -> tuple[str, str]:
    # GitHub Actions forbids secrets named GITHUB_*, so prefer GIST_TOKEN there.
    token   = os.environ.get("GIST_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    gist_id = os.environ.get("MONITOR_STATE_GIST", "") or os.environ.get("GIST_HISTORY_ID", "")
    return token, gist_id


def _load_state() -> dict:
    token, gist_id = _gist_ids()
    if not (token and gist_id):
        return {}
    try:
        r = requests.get(f"https://api.github.com/gists/{gist_id}",
                         headers={"Authorization": f"token {token}"}, timeout=10)
        if r.status_code != 200:
            return {}
        files = r.json().get("files", {})
        if _STATE_FILE in files:
            return json.loads(files[_STATE_FILE].get("content") or "{}")
    except Exception as exc:
        log.warning("state load failed: %s", exc)
    return {}


def _save_state(state: dict) -> None:
    token, gist_id = _gist_ids()
    if not (token and gist_id):
        return
    try:
        requests.patch(f"https://api.github.com/gists/{gist_id}",
                       headers={"Authorization": f"token {token}"},
                       json={"files": {_STATE_FILE: {"content": json.dumps(state)}}},
                       timeout=10)
    except Exception as exc:
        log.warning("state save failed: %s", exc)


# ─────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────

def _ist_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)


def _market_open(ist: datetime) -> bool:
    """MCX commodities trade ~09:00–23:30 IST, Mon–Fri."""
    if ist.weekday() >= 5:
        return False
    mins = ist.hour * 60 + ist.minute
    return 9 * 60 <= mins <= 23 * 60 + 30


def main() -> int:
    ist = _ist_now()
    if not _market_open(ist):
        log.info("MCX closed (%s IST) — nothing to do", ist.strftime("%a %H:%M"))
        return 0

    # 1. Fyers auto-login (TOTP) — credentials from env
    from fyers_fetcher import auto_login, is_auto_login_configured
    if not is_auto_login_configured():
        log.error("Fyers auto-login not configured — set FYERS_* env/secrets")
        return 1
    token, err = auto_login()
    if not token:
        log.error("Fyers auto-login failed: %s", err)
        return 1
    log.info("Fyers connected")

    # 2. SILVERMIC signal — use the SAME tuned thresholds as the app (SM_* env)
    #    so the cron and the SILVERMIC tab generate identical signals.
    def _f(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, default))
        except Exception:
            return float(default)

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
    sig = res.signal
    log.info("SILVERMIC signal = %s", sig)

    today = ist.strftime("%Y-%m-%d")
    state = _load_state()
    last_alerted = state.get("last_alerted", "WAIT") if state.get("date") == today else "WAIT"

    # 3. Not LONG → reset dedup so the next LONG alerts, then exit
    if sig != "LONG":
        _save_state({"last_alerted": "WAIT", "date": today})
        return 0

    # Already alerted this LONG episode → don't repeat
    if last_alerted == "LONG":
        log.info("Already alerted this LONG episode — skipping")
        return 0

    # 4. DeepSeek gate (skip the alert if the AI says it's not tradeable)
    try:
        import deepseek_analyzer as dsa
        if dsa.is_configured():
            verdict = dsa.screen_silvermic({
                "signal": res.signal, "htf": res.htf,
                "entry": res.entry, "news_verdict": res.news_verdict,
            })
            if verdict.ok and verdict.verdict == "AVOID":
                log.info("DeepSeek AVOID — suppressing alert: %s", verdict.reasons[:2])
                return 0   # leave state un-set so it re-evaluates next run
            log.info("DeepSeek verdict = %s (%s%%)", verdict.verdict, verdict.confidence)
        else:
            log.info("DeepSeek not configured — alerting on technical LONG only")
    except Exception as exc:
        log.warning("DeepSeek screen failed (%s) — alerting on technical LONG", exc)

    # 5. Slack alert
    bot   = os.environ.get("SLACK_BOT_TOKEN", "")
    chan  = os.environ.get("SLACK_CHANNEL", "#general")
    if not bot:
        log.error("SLACK_BOT_TOKEN missing — cannot alert")
        return 1
    from notifier import send_slack_alert
    ent  = res.entry or {}
    ep   = ent.get("entry_price", 0)
    nv   = res.news_verdict or {}
    ins  = nv.get("top_insights", [])
    ok = send_slack_alert(bot, chan, {
        "entry":         ep,
        "stop_loss":     ent.get("stop_loss", 0),
        "t1":            round(ep + 1500, 0),
        "t2":            round(ep + 4000, 0),
        "t3":            round(ep + 11000, 0),
        "news_score":    nv.get("score", "N/A"),
        "news_label":    nv.get("label", "N/A"),
        "news_decision": nv.get("decision", "N/A"),
        "top_insight":   ins[0] if ins else "AI-confirmed SILVERMIC LONG",
    })
    if ok:
        log.info("Slack alert sent")
        _save_state({"last_alerted": "LONG", "date": today})
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
