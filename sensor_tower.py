"""Sensor Tower API client for fetching newly released puzzle/casual games."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import re
import threading
import time
from typing import Any
from urllib.parse import urlencode

import requests

from config import load_config

logger = logging.getLogger(__name__)


def _has_latin_chars(text: str) -> bool:
    return bool(re.search(r'[A-Za-z]', text))

PUZZLE_CATEGORY_IDS: dict[str, list[str]] = {
    "ios": [
        "7012",  # Games/Puzzle
        "7003",  # Games/Casual
        "7019",  # Games/Word
        "7004",  # Games/Board
        "7009",  # Games/Family
        "7018",  # Games/Trivia
    ],
    "android": [
        "game_puzzle",
        "game_casual",
        "game_word",
        "game_board",
        "game_trivia",
        "game_arcade",
        "game_card",
        "game_educational",
        "game_family",
    ],
}

MIN_INSTALLS: dict[str, int] = {
    "ios": 0,
    "android": 0,
}

CATEGORY_DISPLAY: dict[str, str] = {
    # iOS numeric IDs
    "7012": "Puzzle",
    "7003": "Casual",
    "7019": "Word",
    "7004": "Board",
    "7009": "Family",
    "7018": "Trivia",
    # Android category slugs
    "game_puzzle": "Puzzle",
    "game_casual": "Casual",
    "game_word": "Word",
    "game_board": "Board",
    "game_trivia": "Trivia",
    "game_arcade": "Arcade",
    "game_card": "Card",
    "game_educational": "Educational",
    "game_family": "Family",
}

BASE_URL = "https://api.sensortower.com"
APP_URL = "https://app.sensortower.com"
MAX_REQUESTS_PER_SECOND = 5.0
APP_IDS_BATCH_SIZE = 50
METADATA_BATCH_SIZE = 100
INSTALL_FETCH_WORKERS = 4
METADATA_FETCH_WORKERS = 3
HTTP_MAX_RETRIES = 4
HTTP_RETRY_BACKOFF_BASE = 2.0

_last_request_time: float = 0.0
_rate_lock = threading.Lock()


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i: i + size] for i in range(0, len(items), size)]


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    s = dict(params)
    s.pop("auth_token", None)
    return s


def _build_log_url(url: str, params: dict[str, Any]) -> str:
    s = _sanitize_params(params)
    return f"{url}?{urlencode(s, doseq=True)}" if s else url


def _throttled_get(url: str, params: dict[str, Any]) -> requests.Response:
    global _last_request_time
    min_interval = 1.0 / MAX_REQUESTS_PER_SECOND
    with _rate_lock:
        elapsed = time.monotonic() - _last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _last_request_time = time.monotonic()
    response = requests.get(url, params=params, timeout=30)
    usage_count = response.headers.get("x-api-usage-count")
    usage_limit = response.headers.get("x-api-usage-limit")
    if usage_count is not None:
        logger.info("Sensor Tower API usage: count=%s limit=%s", usage_count, usage_limit or "unknown")
    return response


def _get_json(url: str, params: dict[str, Any]) -> Any | None:
    log_url = _build_log_url(url, params)
    for attempt in range(1, HTTP_MAX_RETRIES + 1):
        try:
            response = _throttled_get(url, params)
            if response.status_code == 429:
                retry_after_header = response.headers.get("Retry-After")
                try:
                    retry_after = float(retry_after_header) if retry_after_header else 0.0
                except ValueError:
                    retry_after = 0.0
                wait = max(retry_after, HTTP_RETRY_BACKOFF_BASE ** attempt)
                if attempt < HTTP_MAX_RETRIES:
                    logger.warning(
                        "ST 429 rate-limited (attempt %d/%d), sleeping %.1fs: %s",
                        attempt, HTTP_MAX_RETRIES, wait, log_url,
                    )
                    time.sleep(wait)
                    continue
                logger.error("ST 429 exhausted retries: %s", log_url)
                return None
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            body_preview = ""
            if exc.response is not None:
                try:
                    body_preview = exc.response.text[:500]
                except Exception:
                    pass
            if status_code in (500, 502, 503, 504) and attempt < HTTP_MAX_RETRIES:
                wait = HTTP_RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    "ST %s server error (attempt %d/%d), sleeping %.1fs: %s",
                    status_code, attempt, HTTP_MAX_RETRIES, wait, log_url,
                )
                time.sleep(wait)
                continue
            logger.error("ST HTTP error %s status=%s body=%s", log_url, status_code, body_preview)
            return None
        except requests.RequestException as exc:
            if attempt < HTTP_MAX_RETRIES:
                wait = HTTP_RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    "ST request failed (attempt %d/%d), sleeping %.1fs: %s err=%s",
                    attempt, HTTP_MAX_RETRIES, wait, log_url, exc,
                )
                time.sleep(wait)
                continue
            logger.error("ST request failed %s error=%s", log_url, exc)
            return None
        except ValueError as exc:
            logger.error("ST invalid JSON %s error=%s", log_url, exc)
            return None
    return None


def _fetch_app_ids_for_category(
    platform: str, category_id: str, start_date: str, auth_token: str
) -> list[str]:
    url = f"{BASE_URL}/v1/{platform}/apps/app_ids"
    params: dict[str, Any] = {
        "category": category_id,
        "auth_token": auth_token,
        "start_date": start_date,
        "limit": 1000,
        "offset": 0,
    }
    data = _get_json(url, params)
    logger.info(
        "app_ids platform=%s category=%s: type=%s preview=%s",
        platform, category_id, type(data).__name__,
        str(data)[:300] if data is not None else "None",
    )
    app_ids: list[str] = []
    if isinstance(data, list):
        app_ids = [str(a) for a in data if a]
    elif isinstance(data, dict):
        for key in ("app_ids", "ids", "apps", "data", "results"):
            if key in data and isinstance(data[key], list):
                app_ids = [
                    str(item) if not isinstance(item, dict)
                    else str(item.get("app_id") or item.get("id") or item.get("package_name") or "")
                    for item in data[key]
                ]
                break
    logger.info("Category %s on %s: %d app IDs", category_id, platform, len(app_ids))
    return [a for a in app_ids if a]


def _fetch_install_totals(
    platform: str, app_ids: list[str], start_date: str, end_date: str, auth_token: str,
) -> dict[str, dict[str, Any]]:
    import concurrent.futures

    install_map: dict[str, dict[str, Any]] = {}
    install_lock = threading.Lock()
    url = f"{BASE_URL}/v1/{platform}/sales_report_estimates"
    batches = _chunked(app_ids, APP_IDS_BATCH_SIZE)

    def _process_batch(indexed_batch: tuple[int, list[str]]) -> None:
        batch_idx, batch = indexed_batch
        params: dict[str, Any] = {
            "auth_token": auth_token,
            "start_date": start_date,
            "end_date": end_date,
            "date_granularity": "daily",
            "app_ids[]": batch,
        }
        if platform == "ios":
            params["countries[]"] = ["WW"]
        data = _get_json(url, params)
        if not isinstance(data, list):
            if isinstance(data, dict):
                for key in ("data", "results", "estimates"):
                    if key in data and isinstance(data[key], list):
                        data = data[key]
                        break
            if not isinstance(data, list):
                logger.warning("Unexpected install response platform=%s batch=%d", platform, batch_idx + 1)
                return

        with install_lock:
            for row in data:
                if not isinstance(row, dict):
                    continue
                app_id = str(row.get("aid") or row.get("app_id") or row.get("id") or "")
                if not app_id:
                    continue
                installs = int(
                    row.get("iu") or row.get("u") or row.get("units")
                    or row.get("downloads") or row.get("installs") or 0
                )
                country_code = str(
                    row.get("cc") or row.get("c") or row.get("country") or "WW"
                )
                existing = install_map.setdefault(
                    app_id, {"installs_total": 0, "country": "WW", "top_country_installs": -1},
                )
                existing["installs_total"] += installs
                if installs > int(existing["top_country_installs"]):
                    existing["country"] = country_code
                    existing["top_country_installs"] = installs

    with concurrent.futures.ThreadPoolExecutor(max_workers=INSTALL_FETCH_WORKERS) as executor:
        list(executor.map(_process_batch, enumerate(batches)))

    logger.info(
        "install_totals complete platform=%s: %d apps from %d batches.",
        platform, len(install_map), len(batches),
    )
    return install_map


def _normalize_subcategories(raw_value: Any) -> list[str]:
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value if item]
    if isinstance(raw_value, str) and raw_value:
        return [raw_value]
    return []


def _normalize_screenshots(raw_value: Any) -> list[str]:
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value if item]
    return []


def _extract_keywords(raw_value: Any) -> list[str]:
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value if item]
    if isinstance(raw_value, str) and raw_value:
        return [p.strip() for p in raw_value.split(",") if p.strip()]
    return []


def _build_store_url(platform: str, app_id: str) -> str:
    if platform == "ios":
        return f"https://apps.apple.com/app/id{app_id}"
    return f"https://play.google.com/store/apps/details?id={app_id}"


def _extract_metadata_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("apps", "data", "results"):
            val = data.get(key)
            if isinstance(val, list):
                return [item for item in val if isinstance(item, dict)]
    return []


def _fetch_metadata(
    platform: str, app_ids: list[str], auth_token: str
) -> dict[str, dict[str, Any]]:
    import concurrent.futures

    metadata_by_id: dict[str, dict[str, Any]] = {}
    metadata_lock = threading.Lock()
    url = f"{BASE_URL}/v1/{platform}/apps"
    batches = _chunked(app_ids, METADATA_BATCH_SIZE)

    def _process_batch(batch: list[str]) -> None:
        params: dict[str, Any] = {
            "auth_token": auth_token,
            "app_ids[]": batch,
            "country": "US",
        }
        data = _get_json(url, params)
        items = _extract_metadata_items(data)
        if not items:
            logger.warning("Empty metadata batch platform=%s", platform)
            return
        with metadata_lock:
            for item in items:
                raw_id = (
                    item.get("app_id") or item.get("aid")
                    or item.get("id") or item.get("package_name")
                )
                if raw_id is None:
                    continue
                metadata_by_id[str(raw_id)] = item

    with concurrent.futures.ThreadPoolExecutor(max_workers=METADATA_FETCH_WORKERS) as executor:
        list(executor.map(_process_batch, batches))

    logger.info(
        "metadata complete platform=%s: %d apps from %d batches.",
        platform, len(metadata_by_id), len(batches),
    )
    return metadata_by_id



def _fetch_game_intel(
    platform: str, app_ids: list[str], session_cookie: str
) -> dict[str, dict[str, Any]]:
    """Fetch game_intel_data via app.sensortower.com per-app endpoint (session cookie auth)."""
    intel_by_id: dict[str, dict[str, Any]] = {}
    if not session_cookie:
        logger.info("game_intel skipped: no SENSORTOWER_SESSION set")
        return intel_by_id

    headers = {
        "Cookie": f"sensor_tower_session={session_cookie}; locale=en",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://app.sensortower.com/",
    }

    global _last_request_time
    for app_id in app_ids:
        url = f"{APP_URL}/api/{platform}/apps/{app_id}"
        min_interval = 1.0 / MAX_REQUESTS_PER_SECOND
        with _rate_lock:
            elapsed = time.monotonic() - _last_request_time
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            _last_request_time = time.monotonic()
        try:
            r = requests.get(url, params={"country": "US"}, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    intel = data.get("game_intel_data")
                    if intel:
                        intel_by_id[app_id] = intel
            else:
                logger.debug("game_intel app_id=%s status=%d", app_id, r.status_code)
        except Exception as exc:
            logger.warning("game_intel app_id=%s error=%s", app_id, exc)

    logger.info("game_intel complete platform=%s: %d/%d apps.", platform, len(intel_by_id), len(app_ids))
    return intel_by_id


def _combine_game_data(
    platform: str,
    app_id: str,
    installs: dict[str, Any],
    metadata: dict[str, Any],
    intel: dict[str, Any] | None = None,
    source_category: str = "",
) -> dict[str, Any]:
    # --- Basic metadata ---
    publisher = str(
        metadata.get("publisher") or metadata.get("publisher_name")
        or metadata.get("developer") or ""
    )
    name = str(metadata.get("name") or metadata.get("app_name") or "")
    launch_date = str(
        metadata.get("release_date") or metadata.get("first_release_date")
        or metadata.get("published_at") or ""
    )

    # --- Rich description: combine all text fields ---
    description = " ".join(filter(None, [
        str(metadata.get("description") or ""),
        str(metadata.get("short_description") or ""),
        str(metadata.get("promo_text") or ""),
        str(metadata.get("subtitle") or ""),
    ])).strip()

    # --- Category: map raw IDs to display names ---
    def _map_cat(raw: str) -> str:
        return CATEGORY_DISPLAY.get(raw.strip(), "") if raw.strip().isdigit() or raw.strip().startswith("game_") else raw.strip()

    raw_cats = metadata.get("categories") or []
    if isinstance(raw_cats, list) and raw_cats:
        cat_names = [_map_cat(str(c)) for c in raw_cats]
        cat_names = [c for c in cat_names if c and c.lower() not in ("games", "game", "")]
        category_name = cat_names[0] if cat_names else ""
    else:
        raw_cat = str(
            metadata.get("category") or metadata.get("primary_genre")
            or metadata.get("genre") or ""
        )
        category_name = _map_cat(raw_cat) if raw_cat else ""

    # Try richer genre fields iOS/Android may return
    meta_genre = str(
        metadata.get("primary_genre_name") or metadata.get("genre_name")
        or metadata.get("primary_genre") or ""
    ).strip()
    if meta_genre.lower() in ("games", "game", ""):
        meta_genre = ""

    screenshots = _normalize_screenshots(
        metadata.get("screenshots") or metadata.get("screenshot_urls") or []
    )
    keywords = _extract_keywords(metadata.get("keywords") or metadata.get("tags") or [])
    subcategories = _normalize_subcategories(
        metadata.get("subcategories") or metadata.get("genres")
        or metadata.get("genre_names") or []
    )

    # subtitle as extra subcategory signal
    subtitle = str(metadata.get("subtitle") or "").strip()
    if subtitle and subtitle not in subcategories:
        subcategories = [subtitle] + subcategories

    total_installs = int(installs.get("installs_total", 0) or 0)
    icon_url = str(
        metadata.get("icon_url") or metadata.get("icon") or metadata.get("app_icon")
        or metadata.get("icon_url_512") or metadata.get("icon_url_100")
        or metadata.get("icon_url_60") or ""
    )

    # --- Game Intel (Sensor Tower taxonomy) ---
    intel = intel or {}
    intel_category  = str((intel.get("category")  or {}).get("name") or "")
    intel_genre     = str((intel.get("genre")      or {}).get("name") or "")
    intel_sub_genre = str((intel.get("sub_genre")  or {}).get("name") or "")
    intel_theme     = str((intel.get("theme")      or {}).get("name") or "")

    # Fallback for category only — source_category is category-level, not sub_genre
    if not intel_category:
        intel_category = source_category or meta_genre or category_name
    # intel_sub_genre intentionally left empty if taxonomy API returned nothing

    # Inject taxonomy tags into subcategories so relevance.py picks them up
    taxonomy_tags = [
        t for t in [intel_sub_genre, intel_genre, intel_category, intel_theme]
        if t and t != "N/A"
    ]
    if taxonomy_tags:
        subcategories = list(dict.fromkeys(taxonomy_tags + subcategories))

    return {
        "fid": app_id,
        "app_id": app_id,
        "name": name,
        "publisher": publisher,
        "platform": platform,
        "category": category_name,
        "subcategories": subcategories,
        "description": description,
        "keywords": keywords,
        "store_url": _build_store_url(platform, app_id),
        "screenshots": screenshots,
        "icon_url": icon_url,
        "installs_total": total_installs,
        "installs_last_day": total_installs,
        "country": str(installs.get("country", "WW") or "WW"),
        "launch_date": launch_date,
        "intel_category": intel_category,
        "intel_genre": intel_genre,
        "intel_sub_genre": intel_sub_genre,
        "intel_theme": intel_theme,
    }





def _fetch_platform_games(
    platform: str,
    category_ids: list[str],
    release_start_date: str,
    install_end_date: str,
    cutoff_date: Any,
    max_installs: int | None,
    auth_token: str,
    session_cookie: str = "",
) -> list[dict[str, Any]]:
    platform_min = MIN_INSTALLS.get(platform, 500)
    platform_app_ids: list[str] = []
    seen_app_ids: set[str] = set()
    app_id_to_category: dict[str, str] = {}

    unique_category_ids = list(dict.fromkeys(cat.lower() for cat in category_ids))

    for category_id in unique_category_ids:
        app_ids = _fetch_app_ids_for_category(
            platform=platform,
            category_id=category_id,
            start_date=release_start_date,
            auth_token=auth_token,
        )
        display_cat = CATEGORY_DISPLAY.get(category_id, "")
        for app_id in app_ids:
            if app_id not in seen_app_ids:
                seen_app_ids.add(app_id)
                platform_app_ids.append(app_id)
                if display_cat:
                    app_id_to_category[app_id] = display_cat

    if not platform_app_ids:
        logger.info("No app IDs found for platform=%s.", platform)
        return []

    logger.info("Platform=%s: %d unique app IDs.", platform, len(platform_app_ids))

    install_map = _fetch_install_totals(
        platform=platform,
        app_ids=platform_app_ids,
        start_date=release_start_date,
        end_date=install_end_date,
        auth_token=auth_token,
    )

    if not install_map:
        logger.warning("No install data for platform=%s.", platform)
        return []

    surviving_ids: list[str] = []
    below_threshold = above_threshold = 0
    for app_id, install_data in install_map.items():
        total = int(install_data.get("installs_total", 0) or 0)
        if total < 0:
            below_threshold += 1
            continue
        if max_installs is not None and total > max_installs:
            above_threshold += 1
            continue
        surviving_ids.append(app_id)

    logger.info(
        "Platform=%s: %d passed filter (below=%d above_cap=%d).",
        platform, len(surviving_ids), below_threshold, above_threshold,
    )

    if not surviving_ids:
        return []

    metadata_by_id = _fetch_metadata(
        platform=platform,
        app_ids=surviving_ids,
        auth_token=auth_token,
    )

    if not metadata_by_id:
        logger.warning("No metadata for platform=%s.", platform)
        return []

    taxonomy_by_id = _fetch_game_intel(
        platform=platform,
        app_ids=surviving_ids,
        session_cookie=session_cookie,
    )

    games: list[dict[str, Any]] = []
    for app_id in surviving_ids:
        metadata = metadata_by_id.get(app_id)
        installs = install_map.get(app_id)
        if metadata is None or installs is None:
            continue

        intel = taxonomy_by_id.get(app_id)
        game_data = _combine_game_data(
            platform, app_id, installs, metadata,
            intel=intel,
            source_category=app_id_to_category.get(app_id, ""),
        )

        launch_raw = game_data.get("launch_date", "")
        if launch_raw:
            try:
                launch_date = datetime.fromisoformat(str(launch_raw).split("T")[0]).date()
                if launch_date < cutoff_date:
                    continue
            except ValueError:
                pass

        name = game_data.get("name", "")
        if not _has_latin_chars(name):
            continue

        games.append(game_data)

    return games


def fetch_new_games(
    max_installs: int | None = None,
    release_lookback_days: int = 30,
) -> list[dict[str, Any]]:
    """Fetch games released in last N days.

    Lower install threshold (>=500) is enforced inside the platform fetcher;
    no upper bound by default so the daily list captures every casual/puzzle
    game above the lower threshold for the release window.
    """
    import concurrent.futures

    try:
        config = load_config()
    except RuntimeError as exc:
        logger.error("Unable to load config: %s", exc)
        return []

    cutoff_date = (datetime.utcnow() - timedelta(days=release_lookback_days)).date()
    release_start_date = cutoff_date.isoformat()
    install_end_date = datetime.utcnow().date().isoformat()

    logger.info(
        "Fetching games: release_start=%s install_end=%s max=%s",
        release_start_date, install_end_date, max_installs,
    )

    def _fetch(args: tuple) -> list[dict[str, Any]]:
        platform, category_ids = args
        return _fetch_platform_games(
            platform=platform,
            category_ids=category_ids,
            release_start_date=release_start_date,
            install_end_date=install_end_date,
            cutoff_date=cutoff_date,
            max_installs=max_installs,
            auth_token=config.sensor_tower_api_key,
            session_cookie=config.sensortower_session,
        )

    all_games: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(_fetch, (platform, category_ids)): platform
            for platform, category_ids in PUZZLE_CATEGORY_IDS.items()
        }
        for future in concurrent.futures.as_completed(futures):
            platform = futures[future]
            try:
                all_games.extend(future.result())
            except Exception as exc:
                logger.error("Platform=%s fetch failed: %s", platform, exc)

    seen_store_urls: set[str] = set()
    results: list[dict[str, Any]] = []
    for game in all_games:
        store_url = game.get("store_url", "")
        if store_url in seen_store_urls:
            continue
        seen_store_urls.add(store_url)
        results.append(game)

    logger.info("Total games fetched: %d", len(results))
    return results
