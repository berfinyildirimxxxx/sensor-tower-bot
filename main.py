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
from sensor_tower import fetch_new_games
from sheets import write_new_games_to_sheet
from slack import send_summary_message, send_test_message
from sub_genre import get_sub_genres_for_apps

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

def update_web_data(
    scored_games: list[dict[str, Any]],
    sheet_url: str | None,
) -> list[dict[str, Any]]:
    """Merge today's scan into persistent games_data.json.

    Deduplicates by name+publisher, expires games older than RETENTION_DAYS,
    and merges new platform entries onto existing records.
    Returns the list of genuinely new games added this run (delta).
    """
    today = datetime.now(timezone.utc).date().isoformat()
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=RETENTION_DAYS)).isoformat()

    existing_games: list[dict[str, Any]] = []
    old_sheet_url = ""
    if WEB_DATA_PATH.exists():
        try:
            existing_data = json.loads(WEB_DATA_PATH.read_text(encoding="utf-8"))
            existing_games = existing_data.get("games", [])
            old_sheet_url = existing_data.get("sheet_url", "")
        except (json.JSONDecodeError, OSError):
            pass

    before_expire = len(existing_games)
    existing_games = [
        g for g in existing_games
        if str(g.get("added_date") or g.get("first_seen") or today) >= cutoff
    ]
    expired = before_expire - len(existing_games)

    key_to_idx: dict[str, int] = {}
    for i, g in enumerate(existing_games):
        k = _merge_key(g)
        if k and k != "||":
            key_to_idx[k] = i

    new_games: list[dict[str, Any]] = []

    for game in scored_games:
        k = _merge_key(game)

        if not k or k == "||":
            entry = {**game, "added_date": today, "first_seen": today, "last_seen": today}
            new_games.append(entry)
            existing_games.append(entry)
            continue

        if k in key_to_idx:
            existing = existing_games[key_to_idx[k]]
            existing["last_seen"] = today

            existing_plat_names = {
                str(p.get("platform") or "").lower()
                for p in (existing.get("platforms") or [])
            }
            for p in (game.get("platforms") or []):
                pname = str(p.get("platform") or "").lower()
                if pname and pname not in existing_plat_names:
                    existing.setdefault("platforms", []).append(p)
                    existing["installs_total"] = (
                        int(existing.get("installs_total") or 0)
                        + int(p.get("installs_total") or 0)
                    )
                    existing_plat_names.add(pname)

            plat_names = sorted(existing_plat_names)
            existing["platform"] = "+".join(plat_names) if plat_names else existing.get("platform", "")

            if not existing.get("icon_url") and game.get("icon_url"):
                existing["icon_url"] = game["icon_url"]
            if len(str(game.get("description") or "")) > len(str(existing.get("description") or "")):
                existing["description"] = game["description"]
        else:
            entry = {**game, "added_date": today, "first_seen": today, "last_seen": today}
            new_games.append(entry)
            key_to_idx[k] = len(existing_games)
            existing_games.append(entry)

    existing_games.sort(key=lambda g: int(g.get("installs_total") or 0), reverse=True)

    ios_count = sum(1 for g in existing_games if "ios" in str(g.get("platform") or ""))
    android_count = sum(1 for g in existing_games if "android" in str(g.get("platform") or ""))

    payload = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "run_date": today,
        "sheet_url": sheet_url or old_sheet_url or "",
        "total_games_on_site": len(existing_games),
        "today_added_count": len(new_games),
        "today_added_date": today,
        "games": existing_games,
    }

    WEB_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEB_DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "Web data: %d total, %d new today, %d expired",
        len(existing_games), len(new_games), expired,
    )
    return new_games


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

    # 3) Enrich with sub-genre from Sensor Tower Custom Fields API
    config = load_config()
    auth_token = config.sensor_tower_api_key

    all_app_ids: list[str] = []
    for game in merged:
        app_id = str(game.get("app_id") or game.get("fid") or "")
        if app_id:
            all_app_ids.append(app_id)

    sub_genre_map: dict[str, str] = {}
    if auth_token and all_app_ids:
        logger.info("Fetching sub-genres for %d games via Sensor Tower API", len(all_app_ids))
        sub_genre_map = get_sub_genres_for_apps(all_app_ids, auth_token)
        logger.info("Sub-genre enrichment complete: %d/%d matched", len(sub_genre_map), len(all_app_ids))

    enriched: list[dict[str, Any]] = []
    for game in merged:
        app_id = str(game.get("app_id") or game.get("fid") or "")
        enriched.append({
            **game,
            "intel_sub_genre": sub_genre_map.get(app_id, ""),
        })

    logger.info("Enriched %d games with sub-genre data", len(enriched))

    # 4) Web dashboard — merge into persistent JSON, get delta of new games
    sheet_url = _build_sheet_url()
    new_games = update_web_data(enriched, sheet_url=sheet_url)
    logger.info("New games added to radar today: %d", len(new_games))

    # 5) Google Sheets — write only today's new games to a fresh timestamped tab
    try:
        write_new_games_to_sheet(new_games)
    except Exception as exc:
        logger.error("Failed to write new-games tab: %s", exc)

    # 6) Slack summary — match slack.py's send_summary_message signature exactly
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        send_summary_message(
            run_date=run_date,
            total_fetched=len(enriched),
            ios_fetched=ios_raw,
            android_fetched=android_raw,
        )
    except Exception as exc:
        logger.error("Failed to send Slack summary: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
