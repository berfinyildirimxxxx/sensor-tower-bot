"""Orchestration entry point for the Sensor Tower to Slack alert bot."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
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
from sheets import write_to_sheet
from slack import send_game_alert, send_summary_message


def main() -> None:
    """Run the alert pipeline from fetch to Slack delivery."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if "--test" in sys.argv:
        from slack import send_test_message

        ok = send_test_message()
        print("✅ Test message sent" if ok else "❌ Test message failed")
        return

    if "--send-first-game" in sys.argv:
        logging.info("Fetching games to send first one to Slack...")
        games = fetch_new_games(
            min_installs=500,
            max_installs=50000,
            release_lookback_days=60,
        )
        if not games:
            print("❌ No games fetched, cannot test.")
            return
        first_game = games[0]
        
        # Load registry to test dedupe
        registry = load_sent_games()
        if is_already_sent(first_game, registry):
            print(f"⏭  '{first_game.get('name')}' already sent before, skipping (dedupe works!)")
            return
        
        print(f"Sending to Slack: {first_game.get('name')}")
        ok = send_game_alert(
            game=first_game,
            score=85,
            reason="Test alert — gerçek oyun formatı kontrolü",
            mechanic="Test Mechanic",
        )
        if ok:
            mark_as_sent(first_game, registry)
            save_sent_games(registry)
            print("✅ Game alert sent and marked as sent")
        else:
            print("❌ Game alert failed")
        return

    logging.info("Fetching games from Sensor Tower.")
    games = fetch_new_games(
        min_installs=500,
        max_installs=50000,
        release_lookback_days=60,
    )
    logging.info("Fetched %s games.", len(games))
    print(f"Fetched {len(games)} games.")

    for game in games[:3]:
        print(
            f"Sanity check: {game.get('name', '<unknown>')} "
            f"({game.get('installs_last_day', 0)} installs)"
        )

    scored_games: list[dict[str, Any]] = []
    for game in games:
        score, reason, mechanic = score_game(game)
        if score >= 40:
            scored_games.append(
                {
                    "game": game,
                    "score": score,
                    "reason": reason,
                    "mechanic": mechanic,
                }
            )
    logging.info(
        "Scored %d games, %d passed relevance filter (>=70)",
        len(games),
        len(scored_games),
    )
    print(f"Prepared {len(scored_games)} scored games.")

    print("Loading sent games registry...")
    registry = load_sent_games()
    pruned = prune_old_entries(registry, days=90)
    if pruned:
        logging.info("Pruned %d old entries from registry.", pruned)

    print("Filtering already-sent games...")
    unsent_games: list[dict[str, Any]] = []
    for item in scored_games:
        if not is_already_sent(item["game"], registry):
            unsent_games.append(item)
    print(
        f"Found {len(unsent_games)} unsent games "
        f"(filtered out {len(scored_games) - len(unsent_games)} duplicates)."
    )

    print("Sending alerts to Slack...")
    sent_count = 0
    sent_items_for_sheet: list[dict[str, Any]] = []
    try:
        for item in unsent_games:
            sent = send_game_alert(
                item["game"], item["score"], item["reason"], item["mechanic"]
            )
            if sent:
                mark_as_sent(item["game"], registry)
                sent_count += 1
                sent_items_for_sheet.append(item)
    finally:
        save_sent_games(registry)

    run_date = datetime.utcnow().strftime("%Y-%m-%d")
    sheet_url = None
    if sent_items_for_sheet:
        sheet_url = write_to_sheet(sent_items_for_sheet)

    send_summary_message(
        game_count=sent_count,
        sheet_url=sheet_url,
        run_date=run_date,
    )

    print(f"Pipeline complete. Sent {sent_count} alerts.")


if __name__ == "__main__":
    main()
