"""Orchestration entry point for the Sensor Tower to Slack alert bot."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from relevance import score_game
from sensor_tower import fetch_new_games
from sheets import write_to_sheet, write_all_games_to_sheet
from slack import send_summary_message, send_test_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

WEB_DATA_PATH = Path("docs/games_data.json")
WEB_RETENTION_DAYS = 30


def _load_existing_web_data() -> dict[str, Any]:
    if not WEB_DATA_PATH.exists():
        return {"games": []}
    try:
        with WEB_DATA_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"games": []}
            if "games" not in data:
                data["games"] = []
            return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read existing web data: %s", exc)
        return {"games": []}


def _game_key(game: dict[str, Any]) -> str:
    fid = str(game.get("fid") or game.get("app_id") or "")
    platform = str(game.get("platform") or "")
    return f"{platform}:{fid}" if fid else ""


def _merge_web_games(
    existing: list[dict[str, Any]],
    new_games: list[dict[str, Any]],
    today_iso: str,
) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=WEB_RETENTION_DAYS)).date().isoformat()

    by_key: dict[str, dict[str, Any]] = {}
    for g in existing:
        key = _game_key(g)
        if not key:
            continue
        last_seen = g.get("last_seen") or g.get("first_seen") or today_iso
        if last_seen < cutoff:
            continue
        by_key[key] = g

    for g in new_games:
        key = _game_key(g)
        if not key:
            continue
        if key in by_key:
            existing_game = by_key[key]
            existing_game["installs"] = (
                g.get("installs")
                or g.get("installs_total")
                or existing_game.get("installs", 0)
            )
            existing_game["last_seen"] = today_iso
            if g.get("score") is not None:
                existing_game["score"] = g["score"]
            if g.get("mechanic"):
                existing_game["mechanic"] = g["mechanic"]
            if g.get("reason"):
                existing_game["reason"] = g["reason"]
        else:
            entry = dict(g)
            entry["first_seen"] = today_iso
            entry["last_seen"] = today_iso
            by_key[key] = entry

    return list(by_key.values())


def _write_web_data(
    all_games: list[dict[str, Any]],
    total_fetched: int,
    ios_fetched: int,
    android_fetched: int,
) -> None:
    """Update docs/games_data.json with ALL scanned games (no relevance filter)."""
    today_iso = datetime.now(timezone.utc).date().isoformat()
    existing = _load_existing_web_data()
    merged = _merge_web_games(existing.get("games", []), all_games, today_iso)

    payload = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "run_date": today_iso,
        "retention_days": WEB_RETENTION_DAYS,
        "total_fetched_today": total_fetched,
        "ios_fetched_today": ios_fetched,
        "android_fetched_today": android_fetched,
        "total_games_on_site": len(merged),
        "games": merged,
    }

    WEB_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with WEB_DATA_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info(
        "Web data updated: %d games on site, retention=%d days",
        len(merged),
        WEB_RETENTION_DAYS,
    )


def main() -> int:
    args = sys.argv[1:]
    test_mode = "--test" in args
    dry_run = "--dry-run" in args

    if test_mode:
        logger.info("Running in TEST mode — sending Slack test message and exiting")
        send_test_message()
        return 0

    if dry_run:
        logger.info("Running in DRY-RUN mode (no Slack)")

    logger.info("Fetching games from Sensor Tower.")
    games = fetch_new_games(release_lookback_days=60)
    logger.info("Fetched %d total games", len(games))

    ios_count = sum(1 for g in games if g.get("platform") == "ios")
    android_count = sum(1 for g in games if g.get("platform") == "android")
    logger.info("Platform breakdown: iOS=%d, Android=%d", ios_count, android_count)

    # Score every game — relevance.py force-zeros scores below 30
    scored: list[dict[str, Any]] = []
    for g in games:
        score, mechanic, reason = score_game(g)
        entry = dict(g)
        entry["score"] = score
        entry["mechanic"] = mechanic
        entry["reason"] = reason
        scored.append(entry)

    # Write ALL games to "Scanned" sheet
    write_all_games_to_sheet(scored)

    # Write ALL games to "Portfolio Match" sheet too (no filter — user filters in HTML)
    # Sort by installs desc for the sheet
    sorted_for_sheet = sorted(
        scored,
        key=lambda g: int(g.get("installs", 0) or g.get("installs_total", 0) or 0),
        reverse=True,
    )
    sheet_url = write_to_sheet(sorted_for_sheet)

    # All games go to the web dashboard (user filters via HTML)
    _write_web_data(
        all_games=scored,
        total_fetched=len(games),
        ios_fetched=ios_count,
        android_fetched=android_count,
    )

    # Slack: ONLY summary message — no per-game alerts anymore
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not dry_run:
        send_summary_message(
            run_date=run_date,
            total_fetched=len(games),
            ios_fetched=ios_count,
            android_fetched=android_count,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
