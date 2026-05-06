"""Orchestration entry point for the Sensor Tower to Slack alert bot."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from typing import Any

from ai_filter import filter_relevant_games
from dedupe import (
    is_already_sent,
    load_sent_games,
    mark_as_sent,
    prune_old_entries,
    save_sent_games,
)
from sensor_tower import fetch_new_games
from sheets import write_all_games_to_sheet, write_to_sheet
from slack import send_game_alert, send_summary_message


def main() -> None:
    """Run the alert pipeline from fetch to Slack delivery."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # ── Test helpers ────────────────────────────────────────────────────────────
    if "--test" in sys.argv:
        from slack import send_test_message
        ok = send_test_message()
        print("✅ Test message sent" if ok else "❌ Test message failed")
        return

    if "--send-first-game" in sys.argv:
        logging.info("Fetching games to send first one to Slack...")
        games = fetch_new_games(min_installs=500, max_installs=50000, release_lookback_days=60)
        if not games:
            print("❌ No games fetched.")
            return
        first_game = games[0]
        registry = load_sent_games()
        if is_already_sent(first_game, registry):
            print(f"⏭  '{first_game.get('name')}' already sent — dedupe works!")
            return
        print(f"Sending to Slack: {first_game.get('name')}")
        ok = send_game_alert(
            game=first_game,
            score=85,
            reason="Test alert — gerçek oyun format kontrolü",
            mechanic="Test Mechanic",
        )
        if ok:
            mark_as_sent(first_game, registry)
            save_sent_games(registry)
            print("✅ Game alert sent and marked as sent")
        else:
            print("❌ Game alert failed")
        return

    # --dry-run: full pipeline but skip Slack sends
    dry_run = "--dry-run" in sys.argv

    # ── 1. Fetch ─────────────────────────────────────────────────────────────────
    logging.info("Fetching games from Sensor Tower (iOS + Android).")
    games = fetch_new_games(
        min_installs=500,
        max_installs=50000,
        release_lookback_days=60,
    )
    logging.info("Fetched %d games total.", len(games))
    print(f"\n📦 Fetched {len(games)} games (iOS + Android).")

    if not games:
        print("No games found. Exiting.")
        send_summary_message(
            game_count=0,
            sheet_url=None,
            run_date=datetime.utcnow().strftime("%Y-%m-%d"),
        )
        return

    # Sanity check sample
    for game in games[:3]:
        print(
            f"  Sample: {game.get('name', '<unknown>')} "
            f"platform={game.get('platform')} "
            f"installs={game.get('installs_total', 0):,}"
        )

    # ── 2. Write ALL games to sheet (no filter) ──────────────────────────────────
    print(f"\n📊 Writing all {len(games)} games to 'All Games' sheet...")
    write_all_games_to_sheet(games)

    # ── 3. Claude AI relevance filter ───────────────────────────────────────────
    print(f"\n🤖 Running Claude AI relevance filter on {len(games)} games...")
    relevant_items, all_scored_items = filter_relevant_games(
        games,
        min_score=60,
        batch_size=8,
        use_screenshots=True,
    )
    print(
        f"✅ Claude found {len(relevant_items)} relevant games "
        f"(out of {len(all_scored_items)} total)."
    )

    # ── 4. Write relevant games to sheet ─────────────────────────────────────────
    run_date = datetime.utcnow().strftime("%Y-%m-%d")
    sheet_url = None
    if relevant_items:
        print(f"\n📋 Writing {len(relevant_items)} relevant games to 'Relevant' sheet...")
        sheet_url = write_to_sheet(relevant_items)

    # ── 5. Dedupe & Slack alerts ──────────────────────────────────────────────────
    print("\n🔍 Loading sent games registry...")
    registry = load_sent_games()
    pruned = prune_old_entries(registry, days=90)
    if pruned:
        logging.info("Pruned %d old entries from registry.", pruned)

    unsent_items: list[dict[str, Any]] = []
    for item in relevant_items:
        if not is_already_sent(item["game"], registry):
            unsent_items.append(item)

    print(
        f"📬 {len(unsent_items)} unsent relevant games "
        f"(filtered out {len(relevant_items) - len(unsent_items)} already-sent)."
    )

    sent_count = 0
    if dry_run:
        print("\n⚡ --dry-run mode: skipping Slack sends.")
        for item in unsent_items:
            g = item["game"]
            print(
                f"  [DRY RUN] Would send: {g.get('name')} "
                f"score={item['score']} mechanic={item['mechanic']}"
            )
        sent_count = len(unsent_items)
    else:
        print("\n📣 Sending alerts to Slack...")
        try:
            for item in unsent_items:
                sent = send_game_alert(
                    item["game"], item["score"], item["reason"], item["mechanic"]
                )
                if sent:
                    mark_as_sent(item["game"], registry)
                    sent_count += 1
        finally:
            save_sent_games(registry)

    # ── 6. Summary message ────────────────────────────────────────────────────────
    if not dry_run:
        send_summary_message(
            game_count=sent_count,
            sheet_url=sheet_url,
            run_date=run_date,
        )

    print(
        f"\n🏁 Pipeline complete. "
        f"Fetched={len(games)} Relevant={len(relevant_items)} Sent={sent_count}"
    )


if __name__ == "__main__":
    main()
