"""Sensor Tower API client for fetching newly released puzzle/casual games."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import time
from typing import Any
from urllib.parse import urlencode

import requests

from config import load_config

logger = logging.getLogger(__name__)

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

# Platform-specific install thresholds
MIN_INSTALLS: dict[str, int] = {
    "ios": 500,
    "android": 500,
}

BASE_URL = "https://api.sensortower.com"
MAX_REQUESTS_PER_SECOND = 5.0
APP_IDS_BATCH_SIZE = 50
METADATA_BATCH_SIZE = 100

_last_request_time: float = 0.0


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(params)
    sanitized.pop("auth_token", None)
    return sanitized


def _build_log_url(url: str, params: dict[str, Any]) -> str:
    sanitized = _sanitize_params(params)
    if not sanitized:
        return url
    return f"{url}?{urlencode(sanitized, doseq=True)}"


def _throttled_get(url: str, params: dict[str, Any]) -> requests.Response:
    global _last_request_time
    min_interval = 1.0 / MAX_REQUESTS_PER_SECOND
    elapsed = time.monotonic() - _last_request_time
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    response = requests.get(url, params=params, timeout=30)
    _last_request_time = time.monotonic()
    usage_count = response.headers.get("x-api-usage-count")
    usage_limit = response.headers.get("x-api-usage-limit")
    if usage_count is not None:
        logger.info("Sensor Tower API usage: count=%s limit=%s", usage_count, usage_limit or "unknown")
    return response


def _get_json(url: str, params: dict[str, Any]) -> Any | None:
    log_url = _build_log_url(url, params)
    try:
        response = _throttled_get(url, params)
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
        logger.error("Sensor Tower HTTP error for %s status=%s body=%s", log_url, status_code, body_preview)
    except requests.RequestException as exc:
        logger.error("Sensor Tower request failed for %s error=%s", log_url, exc)
    except ValueError as exc:
        logger.error("Sensor Tower returned invalid JSON for %s error=%s", log_url, exc)
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
        "app_ids response for platform=%s category=%s: type=%s preview=%s",
        platform, category_id, type(data).__name__,
        str(data)[:300] if data is not None else "None",
    )
    app_ids: list[str] = []
    if isinstance(data, list):
        app_ids = [str(app_id) for app_id in data if app_id]
    elif isinstance(data, dict):
        for key in ("app_ids", "ids", "apps", "data", "results"):
            if key in data and isinstance(data[key], list):
                app_ids = [
                    str(item) if not isinstance(item, dict)
                    else str(item.get("app_id") or item.get("id") or item.get("package_name") or "")
                    for item in data[key]
                ]
                break
    logger.info("Category %s on %s: found %d app IDs (start_date=%s)", category_id, platform, len(app_ids), start_date)
    return [aid for aid in app_ids if aid]


def _fetch_install_totals(
    platform: str,
    app_ids: list[str],
    start_date: str,
    end_date: str,
    auth_token: str,
) -> dict[str, dict[str, Any]]:
    """Fetch CUMULATIVE install totals since release, summed across all countries and days.

    iOS:     returns 'cc' for country, 'iu' for installs — uses countries[]=WW (already summed)
    Android: returns 'c' for country, 'u' for installs — per country rows, we sum them all
    """
    install_map: dict[str, dict[str, Any]] = {}
    url = f"{BASE_URL}/v1/{platform}/sales_report_estimates"

    batches = _chunked(app_ids, APP_IDS_BATCH_SIZE)
    for batch_idx, batch in enumerate(batches):
        params: dict[str, Any] = {
            "auth_token": auth_token,
            "start_date": start_date,
            "end_date": end_date,
            "date_granularity": "daily",
            "app_ids[]": batch,
        }
        # iOS: WW gives pre-summed worldwide total
        # Android: no WW support — we get per-country rows and sum ourselves
        if platform == "ios":
            params["countries[]"] = ["WW"]

        data = _get_json(url, params)
        logger.info(
            "install_totals platform=%s batch=%d/%d type=%s preview=%s",
            platform, batch_idx + 1, len(batches),
            type(data).__name__,
            str(data)[:200] if data is not None else "None",
        )

        if not isinstance(data, list):
            if isinstance(data, dict):
                for key in ("data", "results", "estimates"):
                    if key in data and isinstance(data[key], list):
                        data = data[key]
                        break
            if not isinstance(data, list):
                logger.warning(
                    "Unexpected install response for platform=%s batch=%d; skipping. type=%s",
                    platform, batch_idx + 1, type(data).__name__,
                )
                continue

        for row in data:
            if not isinstance(row, dict):
                continue

            app_id = str(row.get("aid") or row.get("app_id") or row.get("id") or "")
            if not app_id:
                continue

            # iOS uses 'iu', Android uses 'u' — check both
            installs = int(
                row.get("iu")       # iOS field
                or row.get("u")     # Android field
                or row.get("units")
                or row.get("downloads")
                or row.get("installs")
                or 0
            )
            # iOS uses 'cc', Android uses 'c' — check both
            country_code = str(
                row.get("cc")       # iOS field
                or row.get("c")     # Android field
                or row.get("country")
                or "WW"
            )

            existing = install_map.setdefault(
                app_id,
                {"installs_total": 0, "country": "WW", "top_country_installs": -1},
            )
            # Sum ALL rows — critical for Android which sends one row per country per day
            existing["installs_total"] += installs
            if installs > int(existing["top_country_installs"]):
                existing["country"] = country_code
                existing["top_country_installs"] = installs

    logger.info("install_totals complete platform=%s: %d apps with data.", platform, len(install_map))
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
        return [part.strip() for part in raw_value.split(",") if part.strip()]
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
    metadata_by_id: dict[str, dict[str, Any]] = {}
    url = f"{BASE_URL}/v1/{platform}/apps"
    for batch in _chunked(app_ids, METADATA_BATCH_SIZE):
        params: dict[str, Any] = {
            "auth_token": auth_token,
            "app_ids[]": batch,
            "country": "US",
        }
        data = _get_json(url, params)
        logger.info(
            "metadata response for platform=%s batch_size=%d: type=%s preview=%s",
            platform, len(batch), type(data).__name__,
            str(data)[:300] if data is not None else "None",
        )
        items = _extract_metadata_items(data)
        if not items:
            logger.warning("Empty or failed metadata batch for platform=%s; skipping.", platform)
            continue
        for item in items:
            raw_id = (
                item.get("app_id") or item.get("aid")
                or item.get("id") or item.get("package_name")
            )
            if raw_id is None:
                continue
            metadata_by_id[str(raw_id)] = item
    return metadata_by_id


def _combine_game_data(
    platform: str,
    app_id: str,
    installs: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    category_name = str(
        metadata.get("category") or metadata.get("primary_genre")
        or metadata.get("genre") or ""
    )
    description = str(
        metadata.get("description") or metadata.get("app_description")
        or metadata.get("short_description") or ""
    )
    publisher = str(
        metadata.get("publisher") or metadata.get("publisher_name")
        or metadata.get("developer") or ""
    )
    name = str(metadata.get("name") or metadata.get("app_name") or "")
    launch_date = str(
        metadata.get("release_date") or metadata.get("first_release_date")
        or metadata.get("published_at") or ""
    )
    screenshots = _normalize_screenshots(
        metadata.get("screenshots") or metadata.get("screenshot_urls") or []
    )
    keywords = _extract_keywords(metadata.get("keywords") or metadata.get("tags") or [])
    subcategories = _normalize_subcategories(
        metadata.get("subcategories") or metadata.get("genres")
        or metadata.get("genre_names") or []
    )
    total_installs = int(installs.get("installs_total", 0) or 0)

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
        "installs_total": total_installs,
        "installs_last_day": total_installs,  # legacy key
        "country": str(installs.get("country", "WW") or "WW"),
        "launch_date": launch_date,
    }


def fetch_new_games(
    max_installs: int | None = 50000,
    release_lookback_days: int = 60,
) -> list[dict[str, Any]]:
    """Fetch games released in last release_lookback_days with platform-specific install thresholds.

    iOS:     min 500 installs (worldwide, pre-summed by Sensor Tower)
    Android: min 200 installs (summed across all countries by us)
    Max:     50,000 installs for both platforms
    """
    try:
        config = load_config()
    except RuntimeError as exc:
        logger.error("Unable to load Sensor Tower configuration: %s", exc)
        return []

    cutoff_date = (datetime.utcnow() - timedelta(days=release_lookback_days)).date()
    release_start_date = cutoff_date.isoformat()
    install_end_date = datetime.utcnow().date().isoformat()

    logger.info(
        "Fetching games: release_start=%s install_end=%s ios_min=%d android_min=%d max=%s",
        release_start_date, install_end_date,
        MIN_INSTALLS["ios"], MIN_INSTALLS["android"], max_installs,
    )

    results: list[dict[str, Any]] = []
    seen_store_urls: set[str] = set()

    for platform, category_ids in PUZZLE_CATEGORY_IDS.items():
        platform_min = MIN_INSTALLS.get(platform, 500)
        platform_app_ids: list[str] = []
        seen_app_ids: set[str] = set()

        unique_category_ids = list(dict.fromkeys(cat.lower() for cat in category_ids))

        for category_id in unique_category_ids:
            app_ids = _fetch_app_ids_for_category(
                platform=platform,
                category_id=category_id,
                start_date=release_start_date,
                auth_token=config.sensor_tower_api_key,
            )
            for app_id in app_ids:
                if app_id not in seen_app_ids:
                    seen_app_ids.add(app_id)
                    platform_app_ids.append(app_id)

        if not platform_app_ids:
            logger.info("No app IDs found for platform=%s in the lookback window.", platform)
            continue

        logger.info("Platform=%s: collected %d unique app IDs across all categories.", platform, len(platform_app_ids))

        install_map = _fetch_install_totals(
            platform=platform,
            app_ids=platform_app_ids,
            start_date=release_start_date,
            end_date=install_end_date,
            auth_token=config.sensor_tower_api_key,
        )

        logger.info("Platform=%s: install data returned for %d apps.", platform, len(install_map))

        if not install_map:
            logger.warning("No install data found for platform=%s.", platform)
            continue

        surviving_ids: list[str] = []
        below_threshold = 0
        above_threshold = 0
        for app_id, install_data in install_map.items():
            total = int(install_data.get("installs_total", 0) or 0)
            if total < platform_min:
                below_threshold += 1
                continue
            if max_installs is not None and total > max_installs:
                above_threshold += 1
                continue
            surviving_ids.append(app_id)

        logger.info(
            "Platform=%s: %d apps passed install filter (min=%d, below=%d, above_cap=%d).",
            platform, len(surviving_ids), platform_min, below_threshold, above_threshold,
        )

        if not surviving_ids:
            logger.info("No apps met the install threshold for platform=%s.", platform)
            continue

        metadata_by_id = _fetch_metadata(
            platform=platform,
            app_ids=surviving_ids,
            auth_token=config.sensor_tower_api_key,
        )

        if not metadata_by_id:
            logger.warning("No metadata returned for platform=%s.", platform)
            continue

        for app_id in surviving_ids:
            metadata = metadata_by_id.get(app_id)
            installs = install_map.get(app_id)
            if metadata is None or installs is None:
                continue

            game_data = _combine_game_data(platform, app_id, installs, metadata)

            launch_raw = game_data.get("launch_date", "")
            if launch_raw:
                try:
                    launch_date = datetime.fromisoformat(str(launch_raw).split("T")[0]).date()
                    if launch_date < cutoff_date:
                        logger.debug(
                            "Skipping %s — launch_date %s older than cutoff %s",
                            game_data.get("name"), launch_date, cutoff_date,
                        )
                        continue
                except ValueError:
                    pass

            store_url = game_data.get("store_url", "")
            if store_url in seen_store_urls:
                continue
            seen_store_urls.add(store_url)

            results.append(game_data)

    logger.info("Total games fetched across all platforms: %d", len(results))
    return results
