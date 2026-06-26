#!/usr/bin/env python3
"""
spread_monitor.py — headless SILVERMIC calendar-spread sampler (GitHub Actions cron).

Keeps the Spreads tab's all-time min/max gap-free 24/7, no browser needed:
    MCX open (holiday-aware) → Fyers auto-login (TOTP) → sample the live spread AND
    recent intraday history into the shared min/max (gist). No Slack — pure min/max
    maintenance, written to the SAME gist file the app reads.

Config via ENV (GitHub repo Secrets — the ones you already set):
    FYERS_CLIENT_ID, FYERS_SECRET_KEY, FYERS_ID, FYERS_TOTP_SECRET, FYERS_PIN
    GIST_TOKEN + MONITOR_STATE_GIST   (shared spread state)

Exit 0 on every clean run (including market-closed); only unexpected errors return 1.
"""
from __future__ import annotations

import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [spread-monitor] %(levelname)s: %(message)s")
log = logging.getLogger("spread_monitor")


def main() -> int:
    from mcx_calendar import is_market_open, session_label, ist_now
    ist = ist_now()
    if not is_market_open(ist):
        log.info("MCX closed (%s, %s IST) — nothing to do",
                 session_label(ist), ist.strftime("%a %H:%M"))
        return 0

    from fyers_fetcher import auto_login, is_auto_login_configured
    if not is_auto_login_configured():
        log.error("Fyers auto-login not configured — set FYERS_* secrets")
        return 1
    token, err = auto_login()
    if not token:
        log.error("Fyers auto-login failed: %s", err)
        return 1
    log.info("Fyers connected")

    import silvermic_spread as sps
    n = sps.cron_sample(token)
    if n == 0:
        log.info("No tradeable spread pairs (contracts may not have quoted)")
    else:
        log.info("Sampled %d spread pair(s) into the all-time min/max", n)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log.exception("spread_monitor crashed: %s", exc)
        sys.exit(1)
