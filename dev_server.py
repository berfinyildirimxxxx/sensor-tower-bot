"""Local dev server that fetches live Sensor Tower data on each request."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

from config import load_config
from main import merge_cross_platform
from sensor_tower import fetch_new_games
from sub_genre import get_sub_genres_for_apps

app = Flask(__name__, static_folder="docs", static_url_path="")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 60

_cache: dict[str, Any] | None = None
_cache_lock = threading.Lock()
_fetching = False


def _fetch_all_games() -> dict[str, Any]:
    """Fetch from Sensor Tower, merge, then enrich every result with sub-genre."""
    raw_games = fetch_new_games(
        release_lookback_days=LOOKBACK_DAYS,
    )
    logger.info("Fetched %d raw games from Sensor Tower", len(raw_games))

    merged = merge_cross_platform(raw_games)
    merged.sort(key=lambda g: int(g.get("installs_total") or 0), reverse=True)

    try:
        config = load_config()
        auth_token = config.sensor_tower_api_key
    except Exception:
        auth_token = ""

    all_app_ids = []
    for game in merged:
        app_id = str(game.get("app_id") or game.get("fid") or "")
        if app_id:
            all_app_ids.append(app_id)

    sub_genre_map: dict[str, str] = {}
    if auth_token and all_app_ids:
        logger.info("Fetching sub-genres for all %d games via official API", len(all_app_ids))
        sub_genre_map = get_sub_genres_for_apps(all_app_ids, auth_token)

    minimal_games = []
    for game in merged:
        app_id = str(game.get("app_id") or game.get("fid") or "")
        intel_sub_genre = sub_genre_map.get(app_id, "")

        minimal_games.append({
            "name": game.get("name") or "Unknown",
            "category": game.get("category") or "",
            "intel_category": game.get("intel_category") or game.get("category") or "",
            "intel_sub_genre": intel_sub_genre,
            "platform": game.get("platform") or "",
            "icon_url": game.get("icon_url") or "",
            "store_url": game.get("store_url") or "",
            "publisher": game.get("publisher") or "",
        })

    return {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "run_date": datetime.now(timezone.utc).date().isoformat(),
        "total_fetched_today": len(merged),
        "total_games_on_site": len(minimal_games),
        "games": minimal_games,
    }


@app.route("/")
def index():
    return send_from_directory("docs", "index.html")


@app.route("/api/games")
@app.route("/api/top10")
def api_games():
    global _cache, _fetching
    force_refresh = request.args.get("refresh") == "1"

    if _cache is not None and not force_refresh:
        return jsonify(_cache)

    with _cache_lock:
        if _fetching:
            return jsonify({"status": "loading", "message": "Data is being fetched, please wait..."}), 202
        _fetching = True

    try:
        data = _fetch_all_games()
        _cache = data
        return jsonify(data)
    finally:
        with _cache_lock:
            _fetching = False


if __name__ == "__main__":
    print("Starting dev server at http://localhost:8000")
    print(f"Fetching last {LOOKBACK_DAYS} days, no install cap, showing ALL results")
    print("Sub-genre: using official API (auth_token, no cookie needed)")
    app.run(host="127.0.0.1", port=8000, debug=False)
