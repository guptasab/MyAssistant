"""Slack integration scaffold — optional, activates if SLACK_BOT_TOKEN is set.

Lets Ollie post to channels (status updates) and DM you a daily work briefing.
"""
from __future__ import annotations

from loguru import logger

from ram.core.config import settings
from ram.core.registry import skill


def _client():
    if not getattr(settings, "slack_bot_token", ""):
        return None
    try:
        from slack_sdk import WebClient
        return WebClient(token=settings.slack_bot_token)
    except ImportError:
        logger.warning("slack_sdk not installed — `pip install slack_sdk` to enable Slack")
        return None


@skill(
    name="slack_post",
    description=("Post a message to a Slack channel. channel can be a name (#general) "
                 "or an ID. Set status updates, log decisions, etc."),
    requires=["slack_bot_token"],
    sensitive=True,
)
def slack_post(channel: str, text: str) -> str:
    c = _client()
    if not c:
        return "ERROR: Slack not configured"
    try:
        resp = c.chat_postMessage(channel=channel, text=text)
        return f"posted to {channel} (ts={resp['ts']})"
    except Exception as e:
        return f"ERROR: {e}"


@skill(
    name="slack_dm",
    description="Send yourself a DM in Slack (uses your user id from SLACK_USER_ID).",
    requires=["slack_bot_token", "slack_user_id"],
)
def slack_dm(text: str) -> str:
    c = _client()
    if not c:
        return "ERROR: Slack not configured"
    try:
        resp = c.chat_postMessage(channel=settings.slack_user_id, text=text)
        return f"DM sent (ts={resp['ts']})"
    except Exception as e:
        return f"ERROR: {e}"
