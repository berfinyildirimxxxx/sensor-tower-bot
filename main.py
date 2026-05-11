"""Orchestration entry point for the Sensor Tower to Slack alert bot."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import load_config
from relevance import score_game
from sensor_tower import fetch_new_games
from sheets import write_all_games_to_sheet, write_to_sheet
from slack import send_summary_message, send_test_message

logger = logging.getLogger(__name__)

WEB_DATA_PATH = Path("docs/games_data.json")
RETENTION_DAYS = 30


# ---------------------------------------------------------------------------
# iOS + Android merging
# ---------------------------------------------------------------------------

def _merge_key(game: dict[str, Any]) -> str:
    name = str(game.get("name") or "").strip().lower()
    publisher = str(game.get("publisher") or "").strip().lower()
    return f"{name}||{publisher}"


def _platform_block(game: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform": str(game.get("platform") or "").lower(),
        "app_id": game.get("app_id") or game.get("fid"),
        "installs_total": int(game.get("installs_total") or 0),
        "launch_date": game.get("launch_date") or "",
        "store_url": game.get("store_url") or "",
        "country": game.get("country") or "",
    }


def merge_cross_platform(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge iOS + Android copies of the same game (name + publisher match)."""
    merged: dict[str, dict[str, Any]] = {}

    for game in games:
        if not game.get("name") or not game.get("publisher"):
            key = str(game.get("fid") or game.get("app_id") or id(game))
            merged[key] = {**game, "platforms": [_platform_block(game)]}
            continue

        key = _merge_key(game)
        if key not in merged:
            merged[key] = {**game, "platforms": [_platform_block(game)]}
        else:
            existing = merged[key]
            existing["platforms"].append(_platform_block(game))
            existing["installs_total"] = int(existing.get("installs_total") or 0) + int(game.get("installs_total") or 0)
            if len(str(game.get("description") or "")) > len(str(existing.get("description") or "")):
                existing["description"] = game.get("description")
            if len(game.get("screenshots") or []) > len(existing.get("screenshots") or []):
                existing["screenshots"] = game.get("screenshots")
            if not existing.get("icon_url") and game.get("icon_url"):
                existing["icon_url"] = game.get("icon_url")
            existing_date = str(existing.get("launch_date") or "")
            new_date = str(game.get("launch_date") or "")
            if new_date and (not existing_date or new_date < existing_date):
                existing["launch_date"] = new_date

    out = []
    for entry in merged.values():
        plats = entry.get("platforms") or []
        platform_names = sorted({str(p.get("platform") or "").lower() for p in plats if p.get("platform")})
        entry["platform"] = "+".join(platform_names) if platform_names else entry.get("platform")
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Web data
# ---------------------------------------------------------------------------

def _load_existing_web_data() -> dict[str, Any]:
    if not WEB_DATA_PATH.exists():
        return {"games": [], "last_updated": ""}
    try:
        return json.loads(WEB_DATA_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read existing web data, starting fresh: %s", exc)
        return {"games": [], "last_updated": ""}


def _prune_old_games(games: list[dict[str, Any]], retention_days: int) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).date().isoformat()
    return [g for g in games if str(g.get("first_seen") or "") >= cutoff]


def update_web_data(scored_games: list[dict[str, Any]], sheet_url: str | None) -> None:
    """Merge today's scored games into docs/games_data.json with 30d retention."""
    today = datetime.now(timezone.utc).date().isoformat()
    existing = _load_existing_web_data()
    existing_games: list[dict[str, Any]] = existing.get("games") or []

    by_key: dict[str, dict[str, Any]] = {}
    for g in existing_games:
        key = _merge_key(g)
        by_key[key] = g

    for g in scored_games:
        key = _merge_key(g)
        if key in by_key:
            g["first_seen"] = by_key[key].get("first_seen") or today
        else:
            g["first_seen"] = today
        g["last_seen"] = today
        by_key[key] = g

    all_games = list(by_key.values())
    all_games = _prune_old_games(all_games, RETENTION_DAYS)
    all_games.sort(key=lambda g: int(g.get("installs_total") or 0), reverse=True)

    ios_count = sum(1 for g in scored_games if "ios" in str(g.get("platform") or ""))
    android_count = sum(1 for g in scored_games if "android" in str(g.get("platform") or ""))

    payload = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "run_date": today,
        "retention_days": RETENTION_DAYS,
        "sheet_url": sheet_url or existing.get("sheet_url") or "",
        "total_fetched_today": len(scored_games),
        "ios_fetched_today": ios_count,
        "android_fetched_today": android_count,
        "total_games_on_site": len(all_games),
        "games": all_games,
    }

    WEB_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEB_DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Web data updated: %d games today, %d total on site", len(scored_games), len(all_games))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def _build_sheet_url() -> str | None:
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        return None
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


def main() -> int:
    _setup_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Send a Slack test message and exit")
    args = parser.parse_args()

    if args.test:
        logger.info("Test mode: sending a Slack test message and exiting.")
        send_test_message()
        return 0

    # 1) Fetch — sensor_tower.py loads config internally, no args needed
    raw_games = fetch_new_games()
    logger.info("Fetched %d raw games from Sensor Tower", len(raw_games))

    ios_raw = sum(1 for g in raw_games if str(g.get("platform") or "").lower() == "ios")
    android_raw = sum(1 for g in raw_games if str(g.get("platform") or "").lower() == "android")
    logger.info("Platform breakdown (raw): iOS=%d, Android=%d", ios_raw, android_raw)

    # 2) Merge iOS + Android
    merged = merge_cross_platform(raw_games)
    logger.info("After cross-platform merge: %d unique games", len(merged))

    # 3) Score everything — no threshold filter
    # If Sensor Tower provides intel_sub_genre, use it as mechanic (more accurate)
    scored: list[dict[str, Any]] = []
    for g in merged:
        score, mechanic, reason = score_game(g)
        # Override mechanic with Sensor Tower's own sub_genre if available
        intel_sub = str(g.get("intel_sub_genre") or "").strip()
        if intel_sub and intel_sub != "N/A":
            mechanic = intel_sub
            reason = f"ST sub_genre: {intel_sub}; {reason}"
        scored.append({**g, "score": score, "mechanic": mechanic, "reason": reason})

    logger.info("Scored %d games", len(scored))

    # 4) Google Sheets
    try:
        write_all_games_to_sheet(scored)
    except Exception as exc:
        logger.error("Failed to write all-games tab: %s", exc)

    try:
        relevant_only = [g for g in scored if g["score"] >= 60]
        write_to_sheet(relevant_only)
    except Exception as exc:
        logger.error("Failed to write portfolio-match tab: %s", exc)

    # 5) Web dashboard
    sheet_url = _build_sheet_url()
    update_web_data(scored, sheet_url=sheet_url)

    # 6) Slack summary — match slack.py's send_summary_message signature exactly
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        send_summary_message(
            run_date=run_date,
            total_fetched=len(scored),
            ios_fetched=ios_raw,
            android_fetched=android_raw,
        )
    except Exception as exc:
        logger.error("Failed to send Slack summary: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
