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
from sheets import write_all_games_to_sheet, write_to_sheet
from slack import send_game_alert, send_summary_message

RELEVANCE_THRESHOLD = 60


def main() -> None:
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
        games = fetch_new_games(max_installs=50000, release_lookback_days=60)
        if not games:
            print("❌ No games fetched.")
            return
        first_game = games[0]
        registry = load_sent_games()
        if is_already_sent(first_game, registry):
            print(f"⏭  '{first_game.get('name')}' already sent.")
            return
        score, reason, mechanic = score_game(first_game)
        ok = send_game_alert(game=first_game, score=score, reason=reason, mechanic=mechanic)
        if ok:
            mark_as_sent(first_game, registry)
            save_sent_games(registry)
            print("✅ Sent")
        return

    dry_run = "--dry-run" in sys.argv

    # 1. Fetch
    logging.info("Fetching games from Sensor Tower.")
    games = fetch_new_games(max_installs=50000, release_lookback_days=60)
    logging.info("Fetched %d games total.", len(games))
    print(f"\n📦 Fetched {len(games)} games.")

    if not games:
        send_summary_message(
            game_count=0,
            relevant_count=0,
            sheet_url=None,
            run_date=datetime.utcnow().strftime("%Y-%m-%d"),
            total_fetched=0,
        )
        return

    # Count per platform
    ios_count = sum(1 for g in games if g.get("platform") == "ios")
    android_count = sum(1 for g in games if g.get("platform") == "android")
    print(f"  🍎 iOS: {ios_count} | 🤖 Android: {android_count}")

    # 2. All games → sheet
    print(f"\n📊 Writing {len(games)} games to 'All Games' sheet...")
    write_all_games_to_sheet(games)

    # 3. Score — iOS first, then Android
    print(f"\n🎯 Scoring {len(games)} games...")
    ios_games = [g for g in games if g.get("platform") == "ios"]
    android_games = [g for g in games if g.get("platform") == "android"]
    sorted_games = ios_games + android_games

    scored_games: list[dict[str, Any]] = []
    for game in sorted_games:
        score, reason, mechanic = score_game(game)
        scored_games.append({"game": game, "score": score, "reason": reason, "mechanic": mechanic})

    relevant_games = [g for g in scored_games if g["score"] >= RELEVANCE_THRESHOLD]
    ios_relevant = sum(1 for g in relevant_games if g["game"].get("platform") == "ios")
    android_relevant = sum(1 for g in relevant_games if g["game"].get("platform") == "android")

    logging.info(
        "Scored %d games — %d passed threshold (>=%d). iOS=%d Android=%d",
        len(scored_games), len(relevant_games), RELEVANCE_THRESHOLD,
        ios_relevant, android_relevant,
    )
    print(f"✅ {len(relevant_games)} relevant (🍎 iOS: {ios_relevant} | 🤖 Android: {android_relevant})")

    # 4. Generate web data JSON for GitHub Pages
    try:
        import json, os
        web_data = {
            "last_updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "run_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "total_fetched": len(games),
            "ios_fetched": ios_count,
            "android_fetched": android_count,
            "total_relevant": len(relevant_games),
            "ios_relevant": ios_relevant,
            "android_relevant": android_relevant,
            "games": [
                {
                    "name": item["game"].get("name", ""),
                    "publisher": item["game"].get("publisher", ""),
                    "platform": item["game"].get("platform", ""),
                    "category": item["game"].get("category", ""),
                    "installs": item["game"].get("installs_total", 0),
                    "country": item["game"].get("country", ""),
                    "launch_date": item["game"].get("launch_date", ""),
                    "store_url": item["game"].get("store_url", ""),
                    "screenshots": item["game"].get("screenshots", [])[:3],
                    "description": item["game"].get("description", "")[:500],
                    "score": item["score"],
                    "mechanic": item["mechanic"],
                    "reason": item["reason"],
                }
                for item in relevant_games
            ],
        }
        with open("docs/games_data.json", "w", encoding="utf-8") as f:
            json.dump(web_data, f, ensure_ascii=False, indent=2)
        print("📄 Web data JSON updated (docs/games_data.json)")
    except Exception as exc:
        logging.warning("Could not write web data JSON: %s", exc)

    # 5. Relevant → sheet
    run_date = datetime.utcnow().strftime("%Y-%m-%d")
    sheet_url = None
    if relevant_games:
        print(f"\n📋 Writing {len(relevant_games)} relevant games to sheet...")
        sheet_url = write_to_sheet(relevant_games)

    # 6. Dedupe
    registry = load_sent_games()
    pruned = prune_old_entries(registry, days=90)
    if pruned:
        logging.info("Pruned %d old entries.", pruned)

    unsent_games = [item for item in relevant_games if not is_already_sent(item["game"], registry)]
    print(f"📬 {len(unsent_games)} new to send ({len(relevant_games) - len(unsent_games)} already sent).")

    # 7. Slack — iOS first, then Android
    sent_count = 0
    if dry_run:
        print("\n⚡ --dry-run: skipping Slack.")
        for item in unsent_games:
            print(f"  [DRY RUN] {item['game'].get('name')} platform={item['game'].get('platform')} score={item['score']}")
        sent_count = len(unsent_games)
    else:
        print("\n📣 Sending to Slack (iOS first, then Android)...")
        ios_unsent = [i for i in unsent_games if i["game"].get("platform") == "ios"]
        android_unsent = [i for i in unsent_games if i["game"].get("platform") == "android"]
        ordered_unsent = ios_unsent + android_unsent
        try:
            for item in ordered_unsent:
                sent = send_game_alert(item["game"], item["score"], item["reason"], item["mechanic"])
                if sent:
                    mark_as_sent(item["game"], registry)
                    sent_count += 1
        finally:
            save_sent_games(registry)

    # 8. Summary
    if not dry_run:
        send_summary_message(
            game_count=sent_count,
            relevant_count=len(relevant_games),
            sheet_url=sheet_url,
            run_date=run_date,
            total_fetched=len(games),
            ios_fetched=ios_count,
            android_fetched=android_count,
        )

    print(f"\n🏁 Done. Fetched={len(games)} (iOS={ios_count} Android={android_count}) | Relevant={len(relevant_games)} | Sent={sent_count}")


if __name__ == "__main__":
    main()
