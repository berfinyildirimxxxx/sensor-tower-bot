"""Orchestration entry point for the Sensor Tower to Slack alert bot."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dedupe import (
    is_already_sent,
    load_sent_games,
    mark_as_sent,
    prune_old_entries,
    save_sent_games,
)
from relevance import score_game
from sensor_tower import fetch_new_games
from sheets import write_to_sheet, write_all_games_to_sheet
from slack import send_game_alert, send_summary_message, send_test_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

WEB_DATA_PATH = Path("docs/games_data.json")
WEB_RETENTION_DAYS = 30  # how many days to keep games on the website


def _load_existing_web_data() -> dict[str, Any]:
    """Load previous games_data.json so we can append, not overwrite."""
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
    """Unique identifier for a game across runs."""
    fid = str(game.get("fid") or game.get("app_id") or "")
    platform = str(game.get("platform") or "")
    return f"{platform}:{fid}" if fid else ""


def _merge_web_games(
    existing: list[dict[str, Any]],
    new_relevant: list[dict[str, Any]],
    today_iso: str,
) -> list[dict[str, Any]]:
    """
    Merge new relevant games into existing list.

    Rules:
    - If a game already exists (by platform+fid), update its install count and
      refresh its `last_seen` date but keep it in place.
    - If new, add it with `first_seen` and `last_seen` set to today.
    - Drop any game whose `last_seen` is older than WEB_RETENTION_DAYS.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=WEB_RETENTION_DAYS)).date().isoformat()

    # Index existing games by key
    by_key: dict[str, dict[str, Any]] = {}
    for g in existing:
        key = _game_key(g)
        if not key:
            continue
        # Drop if too old
        last_seen = g.get("last_seen") or g.get("first_seen") or today_iso
        if last_seen < cutoff:
            continue
        by_key[key] = g

    # Merge in new games
    for g in new_relevant:
        key = _game_key(g)
        if not key:
            continue
        if key in by_key:
            # Update install count and last_seen, keep first_seen
            existing_game = by_key[key]
            existing_game["installs"] = (
                g.get("installs")
                or g.get("installs_total")
                or existing_game.get("installs", 0)
            )
            existing_game["last_seen"] = today_iso
            # Refresh score and reason in case relevance logic changed
            if g.get("score") is not None:
                existing_game["score"] = g["score"]
            if g.get("mechanic"):
                existing_game["mechanic"] = g["mechanic"]
            if g.get("reason"):
                existing_game["reason"] = g["reason"]
        else:
            # New game — add with first_seen and last_seen
            entry = dict(g)
            entry["first_seen"] = today_iso
            entry["last_seen"] = today_iso
            by_key[key] = entry

    return list(by_key.values())


def _write_web_data(
    relevant_games: list[dict[str, Any]],
    total_fetched: int,
    ios_fetched: int,
    android_fetched: int,
    total_relevant_today: int,
    ios_relevant_today: int,
    android_relevant_today: int,
) -> None:
    """Update docs/games_data.json with cumulative data."""
    today_iso = datetime.now(timezone.utc).date().isoformat()
    existing = _load_existing_web_data()
    merged = _merge_web_games(existing.get("games", []), relevant_games, today_iso)

    payload = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "run_date": today_iso,
        "retention_days": WEB_RETENTION_DAYS,
        "total_fetched_today": total_fetched,
        "ios_fetched_today": ios_fetched,
        "android_fetched_today": android_fetched,
        "total_relevant_today": total_relevant_today,
        "ios_relevant_today": ios_relevant_today,
        "android_relevant_today": android_relevant_today,
        "total_games_on_site": len(merged),
        "games": merged,
    }

    WEB_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with WEB_DATA_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info(
        "Web data updated: %d new+kept games on site, retention=%d days",
        len(merged),
        WEB_RETENTION_DAYS,
    )


def _installs_of(g: dict[str, Any]) -> int:
    """Get installs from a game dict, handling both key names."""
    return int(g.get("installs", 0) or g.get("installs_total", 0) or 0)


def main() -> int:
    args = sys.argv[1:]
    test_mode = "--test" in args
    dry_run = "--dry-run" in args

    if test_mode:
        logger.info("Running in TEST mode — sending Slack test message and exiting")
        send_test_message()
        return 0

    if dry_run:
        logger.info("Running in DRY-RUN mode (no Slack alerts)")

    logger.info("Fetching games from Sensor Tower.")
    games = fetch_new_games(release_lookback_days=60)
    logger.info("Fetched %d total games", len(games))

    ios_count = sum(1 for g in games if g.get("platform") == "ios")
    android_count = sum(1 for g in games if g.get("platform") == "android")
    logger.info("Platform breakdown: iOS=%d, Android=%d", ios_count, android_count)

    # Score every game
    scored: list[dict[str, Any]] = []
    for g in games:
        score, mechanic, reason = score_game(g)
        entry = dict(g)
        entry["score"] = score
        entry["mechanic"] = mechanic
        entry["reason"] = reason
        scored.append(entry)

    # Write ALL games to "All Games" sheet
    write_all_games_to_sheet(scored)

    # Filter relevant (score >= 60)
    relevant = [g for g in scored if int(g.get("score", 0)) >= 60]
    relevant.sort(key=_installs_of, reverse=True)

    ios_relevant = sum(1 for g in relevant if g.get("platform") == "ios")
    android_relevant = sum(1 for g in relevant if g.get("platform") == "android")

    logger.info(
        "Relevant games: %d (iOS=%d, Android=%d)",
        len(relevant),
        ios_relevant,
        android_relevant,
    )

    # Write relevant to "Relevant" sheet
    relevant_sheet_url = write_to_sheet(relevant)

    # Update web dashboard JSON (cumulative)
    _write_web_data(
        relevant_games=relevant,
        total_fetched=len(games),
        ios_fetched=ios_count,
        android_fetched=android_count,
        total_relevant_today=len(relevant),
        ios_relevant_today=ios_relevant,
        android_relevant_today=android_relevant,
    )

    # Slack alerts (deduped)
    sent_registry = load_sent_games()
    prune_old_entries(sent_registry, days=60)

    sent_count = 0
    if not dry_run:
        # iOS first, then Android — both sorted by installs desc
        ios_relevant_sorted = sorted(
            [g for g in relevant if g.get("platform") == "ios"],
            key=_installs_of,
            reverse=True,
        )
        android_relevant_sorted = sorted(
            [g for g in relevant if g.get("platform") == "android"],
            key=_installs_of,
            reverse=True,
        )
        ordered = ios_relevant_sorted + android_relevant_sorted

        for game in ordered:
            # Correct parameter order for dedupe: game first, registry second
            if is_already_sent(game, sent_registry):
                continue
            # send_game_alert expects: game, score, reason, mechanic
            ok = send_game_alert(
                game=game,
                score=int(game.get("score", 0)),
                reason=str(game.get("reason", "")),
                mechanic=str(game.get("mechanic", "")),
            )
            if ok:
                sent_count += 1
                mark_as_sent(game, sent_registry)

        save_sent_games(sent_registry)
        logger.info("Sent %d new games to Slack", sent_count)
    else:
        logger.info("Dry run: would have sent %d games to Slack", len(relevant))

    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not dry_run:
        send_summary_message(
            game_count=sent_count,
            sheet_url=relevant_sheet_url,
            run_date=run_date,
            total_fetched=len(games),
            relevant_count=len(relevant),
            ios_fetched=ios_count,
            android_fetched=android_count,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
