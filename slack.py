"""Slack Incoming Webhook delivery helpers."""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


def _post_blocks(blocks: list[dict[str, Any]]) -> bool:
    from config import load_config
    try:
        config = load_config()
    except RuntimeError as exc:
        logger.error("Unable to load Slack webhook configuration: %s", exc)
        return False
    try:
        response = requests.post(
            config.slack_webhook_url,
            json={"blocks": blocks},
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.error("Slack webhook request failed: %s", exc)
        return False
    if response.status_code != 200:
        logger.error(
            "Slack webhook failed: status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        return False
    return True


def send_test_message() -> bool:
    """Manual test message for debugging the webhook."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "🧪 *Test message* — Slack webhook is alive.",
            },
        },
    ]
    return _post_blocks(blocks)


def send_summary_message(
    run_date: str,
    total_fetched: int = 0,
    ios_fetched: int = 0,
    android_fetched: int = 0,
) -> bool:
    """Daily summary — only this is sent to Slack now.

    Per-game alerts have been removed. Browse games on the Radar Dashboard.
    """
    lines = [f"📊 *Daily Casual Game Scan — {run_date}*", ""]

    if total_fetched > 0:
        lines.append(f"🔍 *{total_fetched:,}* casual games scanned")

    if ios_fetched or android_fetched:
        lines.append("")
        lines.append(f"🍎 iOS: *{ios_fetched:,}*")
        lines.append(f"🤖 Android: *{android_fetched:,}*")

    lines.append("")
    web_url = "https://berfinyildirimxxxx.github.io/sensor-tower-bot"
    lines.append(f"🌐 <{web_url}|Open Radar Dashboard>")

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(lines)},
        },
    ]
    return _post_blocks(blocks)
