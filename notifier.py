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

    entry = payload.get("entry", 0)
    sl    = payload.get("stop_loss", 0)
    risk  = round(entry - sl, 0) if entry and sl else "N/A"
    t1    = payload.get("t1", round(entry + 1500, 0))
    t2    = payload.get("t2", round(entry + 4000, 0))
    t3    = payload.get("t3", round(entry + 11000, 0))

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🟢 SILVERMIC LONG SETUP", "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Entry Price*\n₹{entry:,.0f}"},
                {"type": "mrkdwn", "text": f"*Stop Loss*\n₹{sl:,.0f}"},
                {"type": "mrkdwn", "text": f"*Risk/Lot*\n₹{risk:,.0f}"},
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
