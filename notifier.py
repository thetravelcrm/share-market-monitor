"""
notifier.py — Send trade alerts via Slack Incoming Webhook.
"""
from __future__ import annotations
import logging
import requests

logger = logging.getLogger(__name__)


def send_slack_alert(webhook_url: str, payload: dict) -> bool:
    """
    Post a formatted Slack message when SILVERMIC LONG SETUP fires.

    payload keys: entry, stop_loss, news_score, news_label,
                  news_decision, top_insight
    Returns True on success.
    """
    if not webhook_url or not webhook_url.startswith("https://hooks.slack.com/"):
        logger.warning("Invalid Slack webhook URL — alert skipped")
        return False

    entry = payload.get("entry", 0)
    sl    = payload.get("stop_loss", 0)
    risk  = round(entry - sl, 0) if entry and sl else "N/A"

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
        resp = requests.post(webhook_url, json={"blocks": blocks}, timeout=8)
        if resp.status_code == 200:
            logger.info("Slack alert sent successfully")
            return True
        logger.warning("Slack alert failed: %s %s", resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.warning("Slack alert exception: %s", e)
        return False
