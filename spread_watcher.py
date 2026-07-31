#!/usr/bin/env python3
"""
spread_watcher.py — near-real-time SILVERMIC spread watcher (~5s sampling).

GitHub's cron can't fire every few seconds, so this script IS the loop: one Actions
job wakes on schedule, then samples the live spreads every ~5 seconds for --minutes,
firing the shared threshold alerts (silvermic_spread._alerts, gist-deduped with the
app and spread_monitor) within seconds of a crossing. All-time/today min-max extremes
accumulate in memory and persist to the gist in one write every ~5 minutes.

Gist traffic is kept tiny:
  - alert LEVELS refresh from the gist once a minute (picks up UI edits),
  - the gist-backed crossing check runs ONLY when the cached view says a fire or a
    re-arm is possible (a sustained breach costs zero extra calls).

Config via ENV (same GitHub secrets as the other monitors):
    FYERS_* , GIST_TOKEN + MONITOR_STATE_GIST , SLACK_BOT_TOKEN + SLACK_CHANNEL
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [spread-watcher] %(levelname)s: %(message)s")
log = logging.getLogger("spread_watcher")

SAMPLE_SECS            = 5      # target sampling cadence
CONTRACTS_REFRESH_SECS = 600    # tradeable-contract list refresh (rolls are slow)
CONFIG_REFRESH_SECS    = 60     # alert-levels refresh from the gist
PERSIST_SECS           = 300    # min/max fold -> gist (one write)
PNL_CHECK_SECS         = 30     # live-position P&L alert cadence


def _maybe_crossing(spreads: list[dict], cfg: dict) -> bool:
    """Cheap pre-check on the cached config: is a FIRE or a RE-ARM possible? Only
    then is the gist-backed check_spread_alerts() (load + maybe save) worth calling."""
    for sp in spreads:
        c = cfg.get(sp["key"])
        if not c:
            continue
        v, hi, lo = sp["spread"], c.get("high"), c.get("low")
        if hi is not None and ((v >= hi and not c.get("fired_high"))
                               or (v < hi and c.get("fired_high"))):
            return True
        if lo is not None and ((v <= lo and not c.get("fired_low"))
                               or (v > lo and c.get("fired_low"))):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=75, help="max runtime in minutes")
    args = ap.parse_args()

    from mcx_calendar import is_market_open, ist_now
    if not is_market_open(ist_now()):
        log.info("MCX closed (%s IST) — nothing to watch", ist_now().strftime("%a %H:%M"))
        return 0

    from fyers_fetcher import auto_login, is_auto_login_configured
    if not is_auto_login_configured():
        log.error("Fyers auto-login not configured — set FYERS_* secrets")
        return 1
    token, err = auto_login()
    if not token:
        log.error("Fyers auto-login failed: %s", err)
        return 1

    import silvermic_spread as sps
    from notifier import send_slack_text
    bot  = os.environ.get("SLACK_BOT_TOKEN", "")
    chan = os.environ.get("SLACK_CHANNEL", "#general")
    log.info("Fyers connected — sampling every %ss for up to %d min (alerts -> %s)",
             SAMPLE_SECS, args.minutes, chan if bot else "DISABLED: no SLACK_BOT_TOKEN")

    deadline = time.time() + args.minutes * 60
    contracts: list[dict] = []
    syms: list[str] = []
    cfg: dict = {}
    pending: dict = {}          # key -> {label, min:(v,ts), max:(v,ts)}
    t_contracts = t_config = t_persist = t_pnl = 0.0
    samples = alerts_sent = 0
    from fyers_fetcher import get_positions

    while time.time() < deadline:
        tick_t0 = time.time()
        if not is_market_open(ist_now()):
            log.info("MCX closed — stopping watcher")
            break

        now = time.time()
        if now - t_contracts > CONTRACTS_REFRESH_SECS or not contracts:
            try:
                contracts = sps.tradeable_contracts(token)
                syms = [c["quote_sym"] for c in contracts]
                t_contracts = now
                log.info("tradeable: %s", [c["label"] for c in contracts] or "none")
            except Exception as e:
                log.warning("contract refresh failed: %s", e)
        if now - t_config > CONFIG_REFRESH_SECS:
            try:
                cfg = sps.get_alert_config()
                t_config = now
            except Exception:
                pass

        spreads: list[dict] = []
        try:
            quotes = sps.quote_many(syms, token)
            priced = []
            for c in contracts:
                q = quotes.get(c["quote_sym"])
                if q and q.get("last_price", 0) > 0:
                    priced.append({**c, "price": round(q["last_price"], 2)})
            if len(priced) >= 2:
                spreads = sps.pairwise_spreads(priced)
        except Exception as e:
            log.warning("sample failed: %s", e)

        if spreads:
            samples += 1
            ts = datetime.now(timezone.utc).isoformat()
            for sp in spreads:
                p = pending.setdefault(sp["key"], {"label": sp["label"],
                                                   "min": (sp["spread"], ts),
                                                   "max": (sp["spread"], ts)})
                if sp["spread"] < p["min"][0]:
                    p["min"] = (sp["spread"], ts)
                if sp["spread"] > p["max"][0]:
                    p["max"] = (sp["spread"], ts)

            if cfg and _maybe_crossing(spreads, cfg):
                try:
                    events = sps.check_spread_alerts(spreads)   # gist-deduped truth
                    cfg = sps.get_alert_config()                # adopt fresh flags
                    t_config = time.time()
                    for ev in events:
                        txt = sps.alert_text(ev)
                        if bot and send_slack_text(bot, chan, txt):
                            alerts_sent += 1
                            log.info("ALERT sent: %s", txt)
                        else:
                            log.error("ALERT Slack send failed: %s", txt)
                except Exception as e:
                    log.warning("alert check failed: %s", e)

        # ── Live-position P&L alerts (~every 30s; same once-per-crossing dedup) ──
        if time.time() - t_pnl > PNL_CHECK_SECS:
            t_pnl = time.time()
            try:
                if sps.get_pnl_alert():                 # only when levels are set
                    posd = get_positions(token)
                    if posd is not None:
                        for ev in sps.check_pnl_alert(posd["total_pl"]):
                            txt = sps.pnl_alert_text(ev)
                            if bot and send_slack_text(bot, chan, txt):
                                alerts_sent += 1
                                log.info("P&L ALERT sent: %s", txt)
                            else:
                                log.error("P&L ALERT Slack send failed: %s", txt)
            except Exception as e:
                log.warning("pnl check failed: %s", e)

        if pending and (time.time() - t_persist > PERSIST_SECS):
            try:
                sps.watcher_persist(pending)
                pending = {}
                t_persist = time.time()
            except Exception as e:
                log.warning("persist failed: %s", e)

        time.sleep(max(0.5, SAMPLE_SECS - (time.time() - tick_t0)))

    if pending:
        try:
            sps.watcher_persist(pending)
        except Exception:
            pass
    log.info("watcher done — %d samples, %d alert(s) sent", samples, alerts_sent)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log.exception("spread_watcher crashed: %s", exc)
        sys.exit(1)
