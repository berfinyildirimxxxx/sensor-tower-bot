"""Slack Incoming Webhook delivery helpers."""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

RADAR_URL = "https://berfinyildirimxxxx.github.io/sensor-tower-bot"


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
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "🧪 *Test message* — Slack webhook is alive."},
        },
    ]
    return _post_blocks(blocks)


def send_summary_message(
    run_date: str,
    total_fetched: int = 0,
    new_today: int = 0,
    ios_fetched: int = 0,
    android_fetched: int = 0,
) -> bool:
    """Daily summary sent to Slack.

    Shows total scanned count and platform breakdown.
    No game names — browse on the dashboard.
    """
    lines = [f"📊 *Daily Casual Game Scan — {run_date}*", ""]
    lines.append(f"🔍 *{total_fetched:,}* games scanned")
    if ios_fetched or android_fetched:
        lines.append(f"📱 iOS: *{ios_fetched:,}*  •  🤖 Android: *{android_fetched:,}*")
    if new_today:
        lines.append(f"🆕 *{new_today:,}* new on radar today")
    lines.append("")
    lines.append(f"🌐 <{RADAR_URL}|Open Radar Dashboard>")

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(lines)},
        },
    ]
    return _post_blocks(blocks)
