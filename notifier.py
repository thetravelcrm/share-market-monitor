"""
notifier.py — Send trade alerts via Slack Bot API (chat.postMessage).
"""
from __future__ import annotations
import logging
import requests

logger = logging.getLogger(__name__)

_SLACK_API = "https://slack.com/api/chat.postMessage"


def send_slack_alert(bot_token: str, channel: str, payload: dict) -> bool:
    """
    Post a formatted Slack message using a Bot OAuth Token.

    bot_token: xoxb-... token from Slack app settings
    channel:   "#general" or channel ID like "C01234ABCD"
    payload keys: entry, stop_loss, news_score, news_label,
                  news_decision, top_insight
    Returns True on success.
    """
    if not bot_token or not bot_token.startswith("xoxb-"):
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
            logger.info("Slack alert sent to %s", channel)
            return True
        logger.warning("Slack alert failed: %s", data.get("error", "unknown"))
        return False
    except Exception as e:
        logger.warning("Slack alert exception: %s", e)
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
