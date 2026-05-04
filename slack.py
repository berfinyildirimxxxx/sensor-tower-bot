"""Slack Incoming Webhook delivery helpers."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

MAX_SCREENSHOTS = 4
MAX_TEXT_LENGTH = 200


def _truncate_text(value: Any, default: str) -> str:
    """Convert a value to text, apply a default, and truncate long content."""
    text = str(value).strip() if value is not None else ""
    if not text:
        text = default
    if len(text) > MAX_TEXT_LENGTH:
        return f"{text[: MAX_TEXT_LENGTH - 3]}..."
    return text


def _normalize_installs(value: Any) -> int:
    """Convert an installs-like value to an integer with a safe fallback."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _platform_label(platform: Any) -> str:
    """Return a friendly platform label with emoji."""
    normalized = str(platform).strip().lower() if platform is not None else ""
    if normalized == "ios":
        return "🍎 iOS"
    if normalized == "android":
        return "🤖 Android"
    return "?"


def _format_release_date(value: Any) -> str:
    """Format ISO date string to YYYY-MM-DD. Return '?' if empty/invalid."""
    text = str(value or "").strip()
    if not text:
        return "?"
    if "T" in text:
        return text.split("T")[0]
    return text


def _valid_screenshot_urls(game: dict[str, Any]) -> list[str]:
    """Return up to four valid HTTP(S) screenshot URLs from a game payload."""
    raw_screenshots = game.get("screenshots", [])
    if not isinstance(raw_screenshots, list):
        return []

    screenshots: list[str] = []
    for item in raw_screenshots:
        url = str(item).strip()
        if url.startswith("http://") or url.startswith("https://"):
            screenshots.append(url)
        if len(screenshots) >= MAX_SCREENSHOTS:
            break
    return screenshots


def _post_blocks(blocks: list[dict[str, Any]]) -> bool:
    """Post a Block Kit payload to the configured Slack webhook."""
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
    """Send a simple test message to verify webhook setup."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "🧪 Bot test mesajı — Slack bağlantısı çalışıyor",
            },
        }
    ]
    return _post_blocks(blocks)


def send_game_alert(
    game: dict[str, Any],
    score: int,
    reason: str,
    mechanic: str,
) -> bool:
    """Post a formatted alert about one game to the configured Slack channel."""
    name = _truncate_text(game.get("name"), "?")
    publisher = _truncate_text(game.get("publisher"), "?")
    country = _truncate_text(game.get("country"), "?")
    release_date = _format_release_date(game.get("launch_date"))
    installs = _normalize_installs(game.get("installs_last_day"))
    platform = _platform_label(game.get("platform"))
    relevance = _normalize_installs(score)
    mechanic_text = _truncate_text(mechanic, "Unknown")
    reason_text = _truncate_text(reason, "?")
    store_url = _truncate_text(game.get("store_url"), "?")
    screenshots = _valid_screenshot_urls(game)

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🎮 {name}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*👤 Developer:*\n{publisher}"},
                {"type": "mrkdwn", "text": f"*📱 Platform:*\n{platform}"},
                {"type": "mrkdwn", "text": f"*🌍 Country:*\n{country}"},
                {"type": "mrkdwn", "text": f"*📅 Release:*\n{release_date}"},
                {"type": "mrkdwn", "text": f"*📊 Installs:*\n{installs:,}"},
                {"type": "mrkdwn", "text": f"*⭐ Relevance:*\n{relevance}/100"},
                {"type": "mrkdwn", "text": f"*🎯 Mechanic:*\n{mechanic_text}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*💡 Why relevant:*\n{reason_text}",
            },
        },
    ]

    if store_url.startswith("http://") or store_url.startswith("https://"):
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "📲 Open in Store",
                        },
                        "url": store_url,
                    }
                ],
            }
        )

    for index, screenshot_url in enumerate(screenshots, start=1):
        blocks.append(
            {
                "type": "image",
                "image_url": screenshot_url,
                "alt_text": f"Screenshot {index}",
            }
        )

    blocks.extend(
        [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "📡 Sensor Tower data · "
                            f"{datetime.utcnow().date().isoformat()}"
                        ),
                    }
                ],
            },
            {"type": "divider"},
        ]
    )

    return _post_blocks(blocks)


def send_summary_message(game_count: int, sheet_url: str | None, run_date: str) -> bool:
    """Send a daily summary message to Slack.

    Format:
    📊 Daily Game Scan Complete — {run_date}
    🎮 {game_count} new relevant games found today
    🔗 View in Google Sheets: {sheet_url}   ← only if sheet_url is not None
    """
    lines = [
        f"📊 Daily Game Scan Complete — {run_date}",
        f"🎮 {game_count} new relevant games found today",
    ]
    if sheet_url:
        lines.append(f"🔗 View in Google Sheets: {sheet_url}")

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(lines),
            },
        }
    ]
    return _post_blocks(blocks)
