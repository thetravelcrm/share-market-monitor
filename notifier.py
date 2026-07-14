"""
notifier.py — Send trade alerts via Slack Bot API (chat.postMessage).
"""
from __future__ import annotations
import logging
import requests

logger = logging.getLogger(__name__)

_SLACK_API = "https://slack.com/api/chat.postMessage"

# Exact reason the most recent Slack send failed (Slack's own `error` code, e.g.
# "not_in_channel", "invalid_auth", "channel_not_found"). "" when the last send was OK.
# Callers (e.g. the Test Alert button) read this to show an actionable message.
LAST_ERROR: str = ""


def send_slack_text(bot_token: str, channel: str, text: str) -> bool:
    """Post a plain-text Slack message (generic alerts, e.g. spread thresholds)."""
    global LAST_ERROR
    if not bot_token or not bot_token.startswith("xoxb-"):
        LAST_ERROR = "bad_token_format"
        logger.warning("Invalid Slack bot token — text alert skipped")
        return False
    try:
        resp = requests.post(_SLACK_API, headers={"Authorization": f"Bearer {bot_token}"},
                             json={"channel": channel, "text": text}, timeout=10)
        data = resp.json()
        if data.get("ok"):
            LAST_ERROR = ""
            return True
        LAST_ERROR = data.get("error", "unknown")
        logger.warning("Slack text alert failed: %s", LAST_ERROR)
        return False
    except Exception as e:
        LAST_ERROR = f"exception: {e}"
        logger.warning("Slack text alert exception: %s", e)
        return False


def send_slack_alert(bot_token: str, channel: str, payload: dict) -> bool:
    """
    Post a formatted Slack message using a Bot OAuth Token.

    bot_token: xoxb-... token from Slack app settings
    channel:   "#general" or channel ID like "C01234ABCD"
    payload keys: entry, stop_loss, news_score, news_label,
                  news_decision, top_insight
    Returns True on success.
    """
    global LAST_ERROR
    if not bot_token or not bot_token.startswith("xoxb-"):
        LAST_ERROR = "bad_token_format"
        logger.warning("Invalid Slack bot token — alert skipped")
        return False

    def _num(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    entry = _num(payload.get("entry", 0))
    sl    = _num(payload.get("stop_loss", 0))
    risk  = round(entry - sl, 0) if entry and sl else None
    risk_text = f"₹{risk:,.0f}" if risk is not None else "N/A"
    t1    = _num(payload.get("t1", round(entry + 1500, 0)))
    t2    = _num(payload.get("t2", round(entry + 4000, 0)))
    t3    = _num(payload.get("t3", round(entry + 11000, 0)))

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text",
                     "text": payload.get("header", "🟢 SILVERMIC LONG SETUP"),
                     "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Entry Price*\n₹{entry:,.0f}"},
                {"type": "mrkdwn", "text": f"*Stop Loss*\n₹{sl:,.0f}"},
                {"type": "mrkdwn", "text": f"*Risk/Lot*\n{risk_text}"},
                {"type": "mrkdwn", "text": f"*News Score*\n{payload.get('news_score', 'N/A')}/10 — {payload.get('news_label', '')}"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*T1 (Cushion)*\n₹{t1:,.0f}  (+₹1,500)"},
                {"type": "mrkdwn", "text": f"*T2 (Mid)*\n₹{t2:,.0f}  (+₹4,000)"},
                {"type": "mrkdwn", "text": f"*T3 (Big)*\n₹{t3:,.0f}  (+₹11,000)"},
                {"type": "mrkdwn", "text": f"*R:R (T1)*\n1:{round((t1-entry)/max(entry-sl,1),1)}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Top Insight:* {payload.get('top_insight', 'N/A')}",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"News decision: *{payload.get('news_decision', 'N/A')}* | Signal generated at market time",
                }
            ],
        },
    ]

    try:
        resp = requests.post(
            _SLACK_API,
            headers={"Authorization": f"Bearer {bot_token}"},
            json={"channel": channel, "blocks": blocks},
            timeout=8,
        )
        data = resp.json()
        if data.get("ok"):
            LAST_ERROR = ""
            logger.info("Slack alert sent to %s", channel)
            return True
        LAST_ERROR = data.get("error", "unknown")
        logger.warning("Slack alert failed: %s", LAST_ERROR)
        return False
    except Exception as e:
        LAST_ERROR = f"exception: {e}"
        logger.warning("Slack alert exception: %s", e)
        return False


def send_perfect_stock_alert(bot_token: str, channel: str, payload: dict) -> bool:
    """
    Slack alert for a news-driven stock PERFECT ENTRY (all 3 gates passed).
    payload keys: symbol, name, action, entry, stop, target, rr, ai_conf, reason
    """
    if not bot_token or not bot_token.startswith("xoxb-"):
        logger.warning("Invalid Slack bot token — perfect-entry alert skipped")
        return False
    sym    = payload.get("symbol", "")
    name   = payload.get("name", "")
    action = payload.get("action", "BUY")
    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"🎯 PERFECT ENTRY — {action} {sym}", "emoji": True}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Stock*\n{name} ({sym})"},
            {"type": "mrkdwn", "text": f"*Action*\n{action}"},
            {"type": "mrkdwn", "text": f"*Entry*\n{payload.get('entry', 'N/A')}"},
            {"type": "mrkdwn", "text": f"*Stop / Target*\nSL {payload.get('stop', 'N/A')} · T {payload.get('target', 'N/A')}"},
            {"type": "mrkdwn", "text": f"*R:R*\n{payload.get('rr', 'N/A')}"},
            {"type": "mrkdwn", "text": f"*AI Conviction*\n{payload.get('ai_conf', 'N/A')}%"},
        ]},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": f"*Why:* {payload.get('reason', 'N/A')}"}},
        {"type": "context",
         "elements": [{"type": "mrkdwn",
                       "text": "Technical + News + DeepSeek (Pro) all CONFIRMED · not financial advice"}]},
    ]
    try:
        resp = requests.post(_SLACK_API, headers={"Authorization": f"Bearer {bot_token}"},
                             json={"channel": channel, "blocks": blocks}, timeout=8)
        data = resp.json()
        if data.get("ok"):
            logger.info("Perfect-entry Slack alert sent for %s", sym)
            return True
        logger.warning("Perfect-entry alert failed: %s", data.get("error", "unknown"))
        return False
    except Exception as e:
        logger.warning("Perfect-entry alert exception: %s", e)
        return False


def send_slack_exit_alert(bot_token: str, channel: str, payload: dict) -> bool:
    """
    Post a SILVERMIC exit alert.

    payload keys: entry_price, exit_price, pnl_rs, exit_reason, final_stop
    Returns True on success.
    """
    if not bot_token or not bot_token.startswith("xoxb-"):
        logger.warning("Invalid Slack bot token — exit alert skipped")
        return False

    entry  = payload.get("entry_price", 0)
    exit_p = payload.get("exit_price", 0)
    pnl    = payload.get("pnl_rs", 0)
    reason = payload.get("exit_reason", "Stop hit")
    stop   = payload.get("final_stop", 0)

    pnl_emoji = "✅" if pnl >= 0 else "🛑"
    header    = f"{pnl_emoji} SILVERMIC EXIT — {reason}"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header, "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Entry Price*\n₹{entry:,.0f}"},
                {"type": "mrkdwn", "text": f"*Exit Price*\n₹{exit_p:,.0f}"},
                {"type": "mrkdwn", "text": f"*P&L*\n₹{pnl:+,.0f}"},
                {"type": "mrkdwn", "text": f"*Final Stop*\n₹{stop:,.0f}"},
            ],
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Exit reason: *{reason}*"}],
        },
    ]

    try:
        resp = requests.post(
            _SLACK_API,
            headers={"Authorization": f"Bearer {bot_token}"},
            json={"channel": channel, "blocks": blocks},
            timeout=8,
        )
        data = resp.json()
        if data.get("ok"):
            logger.info("Slack exit alert sent to %s", channel)
            return True
        logger.warning("Slack exit alert failed: %s", data.get("error", "unknown"))
        return False
    except Exception as e:
        logger.warning("Slack exit alert exception: %s", e)
        return False
