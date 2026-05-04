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

# Sensor Tower category IDs to query.
# TODO(berfin): Verify these IDs against Sensor Tower's Category Ids reference page.
# The exact numeric IDs for puzzle/casual games may differ; replace with correct values
# after checking the Category Ids link in the API docs before using this in production.
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
    ],
}

BASE_URL = "https://api.sensortower.com"
MAX_REQUESTS_PER_SECOND = 5.0
APP_IDS_BATCH_SIZE = 50
METADATA_BATCH_SIZE = 100

_last_request_time: float = 0.0


def _chunked(items: list[str], size: int) -> list[list[str]]:
    """Split a list into smaller lists of the given size."""
    return [items[index : index + size] for index in range(0, len(items), size)]


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of params with the auth token removed for logging."""
    sanitized = dict(params)
    sanitized.pop("auth_token", None)
    return sanitized


def _build_log_url(url: str, params: dict[str, Any]) -> str:
    """Build a log-safe URL string without sensitive query parameters."""
    sanitized = _sanitize_params(params)
    if not sanitized:
        return url
    return f"{url}?{urlencode(sanitized, doseq=True)}"


def _throttled_get(url: str, params: dict[str, Any]) -> requests.Response:
    """Perform a throttled GET request while staying below the API rate limit."""
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
        logger.info(
            "Sensor Tower API usage: count=%s limit=%s",
            usage_count,
            usage_limit or "unknown",
        )

    return response


def _get_json(url: str, params: dict[str, Any]) -> Any | None:
    """Fetch JSON data from Sensor Tower and log any request or decoding failures."""
    log_url = _build_log_url(url, params)
    try:
        response = _throttled_get(url, params)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        logger.error("Sensor Tower HTTP error for %s status=%s", log_url, status_code)
    except requests.RequestException as exc:
        logger.error("Sensor Tower request failed for %s error=%s", log_url, exc)
    except ValueError as exc:
        logger.error("Sensor Tower returned invalid JSON for %s error=%s", log_url, exc)
    return None


def _fetch_app_ids_for_category(
    platform: str, category_id: str, start_date: str, auth_token: str
) -> list[str]:
    """Fetch newly released app IDs for a single platform/category pair."""
    url = f"{BASE_URL}/v1/{platform}/apps/app_ids"
    params: dict[str, Any] = {
        "category": category_id,
        "auth_token": auth_token,
        "start_date": start_date,
        "limit": 1000,
        "offset": 0,
    }
    data = _get_json(url, params)
    if platform == "android":
        if isinstance(data, list):
            logger.info("Android app_ids sample (first 3): %s", data[:3])
        else:
            logger.info(
                "Android app_ids unexpected response: type=%s value=%s",
                type(data).__name__,
                str(data)[:200],
            )

    # Handle different possible response shapes
    app_ids: list[str] = []
    if isinstance(data, list):
        app_ids = [str(app_id) for app_id in data]
    elif isinstance(data, dict):
        # API might wrap response in a dict like {"app_ids": [...]}
        for key in ("app_ids", "ids", "apps", "data"):
            if key in data and isinstance(data[key], list):
                app_ids = [
                    str(item)
                    if not isinstance(item, dict)
                    else str(item.get("app_id") or item.get("id") or "")
                    for item in data[key]
                ]
                break

    logger.info(
        "Category %s on %s: found %d app IDs (start_date=%s)",
        category_id,
        platform,
        len(app_ids),
        start_date,
    )
    return [aid for aid in app_ids if aid]


def _fetch_install_totals(
    platform: str, app_ids: list[str], start_date: str, end_date: str, auth_token: str
) -> dict[str, dict[str, Any]]:
    """Fetch summed install totals and top country per app ID."""
    install_map: dict[str, dict[str, Any]] = {}
    url = f"{BASE_URL}/v1/{platform}/sales_report_estimates"

    for batch in _chunked(app_ids, APP_IDS_BATCH_SIZE):
        params: dict[str, Any] = {
            "auth_token": auth_token,
            "start_date": start_date,
            "end_date": end_date,
            "date_granularity": "daily",
            "app_ids[]": batch,
            "countries[]": ["WW"],
        }
        data = _get_json(url, params)
        if platform == "android":
            if isinstance(data, list):
                logger.info("Android install sample (first 2 rows): %s", data[:2])
            elif isinstance(data, dict):
                logger.info(
                    "Android install response is dict, keys: %s",
                    list(data.keys())[:10],
                )
            else:
                logger.info(
                    "Android install response type=%s value=%s",
                    type(data).__name__,
                    str(data)[:200],
                )
        if not isinstance(data, list):
            logger.warning(
                "Stopping install fetch early for platform=%s after a failed batch request.",
                platform,
            )
            return install_map

        for row in data:
            if not isinstance(row, dict):
                continue

            app_id = str(row.get("aid", ""))
            if not app_id:
                continue

            installs = int(row.get("iu", 0) or 0)
            country_code = str(row.get("cc", "WW") or "WW")
            existing = install_map.setdefault(
                app_id,
                {"installs_last_day": 0, "country": "WW", "top_country_installs": -1},
            )
            existing["installs_last_day"] += installs
            if installs > int(existing["top_country_installs"]):
                existing["country"] = country_code
                existing["top_country_installs"] = installs

    return install_map


def _normalize_subcategories(raw_value: Any) -> list[str]:
    """Normalize metadata subcategory fields into a list of strings."""
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value if item]
    if isinstance(raw_value, str) and raw_value:
        return [raw_value]
    return []


def _normalize_screenshots(raw_value: Any) -> list[str]:
    """Normalize screenshot fields into a list of URL strings."""
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value if item]
    return []


def _extract_keywords(raw_value: Any) -> list[str]:
    """Normalize keyword-like fields from metadata into a list of strings."""
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value if item]
    if isinstance(raw_value, str) and raw_value:
        return [part.strip() for part in raw_value.split(",") if part.strip()]
    return []


def _build_store_url(platform: str, app_id: str) -> str:
    """Build a public store URL from the app ID and platform."""
    if platform == "ios":
        return f"https://apps.apple.com/app/id{app_id}"
    return f"https://play.google.com/store/apps/details?id={app_id}"


def _extract_metadata_items(data: Any) -> list[dict[str, Any]]:
    """Normalize the metadata response into a list of app dictionaries."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        apps_value = data.get("apps")
        if isinstance(apps_value, list):
            return [item for item in apps_value if isinstance(item, dict)]
    return []


def _fetch_metadata(
    platform: str, app_ids: list[str], auth_token: str
) -> dict[str, dict[str, Any]]:
    """Fetch app metadata for a set of app IDs."""
    metadata_by_id: dict[str, dict[str, Any]] = {}
    url = f"{BASE_URL}/v1/{platform}/apps"

    for batch in _chunked(app_ids, METADATA_BATCH_SIZE):
        params: dict[str, Any] = {
            "auth_token": auth_token,
            "app_ids[]": batch,
            "country": "US",
        }
        data = _get_json(url, params)
        items = _extract_metadata_items(data)
        if not items:
            logger.warning(
                "Stopping metadata fetch early for platform=%s after a failed or empty batch.",
                platform,
            )
            return metadata_by_id

        for item in items:
            raw_id = item.get("app_id") or item.get("aid") or item.get("id")
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
    """Combine install totals and metadata into the final game payload."""
    category_name = str(
        metadata.get("category")
        or metadata.get("primary_genre")
        or metadata.get("genre")
        or ""
    )
    description = str(
        metadata.get("description")
        or metadata.get("app_description")
        or metadata.get("short_description")
        or ""
    )
    publisher = str(
        metadata.get("publisher")
        or metadata.get("publisher_name")
        or metadata.get("developer")
        or ""
    )
    name = str(metadata.get("name") or metadata.get("app_name") or "")
    launch_date = str(
        metadata.get("release_date")
        or metadata.get("first_release_date")
        or metadata.get("published_at")
        or ""
    )
    screenshots = _normalize_screenshots(
        metadata.get("screenshots") or metadata.get("screenshot_urls") or []
    )
    keywords = _extract_keywords(metadata.get("keywords") or metadata.get("tags") or [])
    subcategories = _normalize_subcategories(
        metadata.get("subcategories")
        or metadata.get("genres")
        or metadata.get("genre_names")
        or []
    )

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
        "installs_last_day": int(installs.get("installs_last_day", 0) or 0),
        "country": str(installs.get("country", "WW") or "WW"),
        "launch_date": launch_date,
    }


def fetch_new_games(
    min_installs: int = 500,
    max_installs: int | None = None,
    release_lookback_days: int = 30,
) -> list[dict[str, Any]]:
    """Fetch games released recently and sum their installs since release.

    This queries games released in the last ``release_lookback_days`` days,
    then sums installs across the full release window through today. On
    unrecoverable errors, the function logs the issue and returns any data
    collected so far, or an empty list if nothing usable was fetched.
    """
    try:
        config = load_config()
    except RuntimeError as exc:
        logger.error("Unable to load Sensor Tower configuration: %s", exc)
        return []

    cutoff_date = (datetime.utcnow() - timedelta(days=release_lookback_days)).date()
    release_start_date = cutoff_date.isoformat()
    install_end_date = datetime.utcnow().date().isoformat()

    results: list[dict[str, Any]] = []

    for platform, category_ids in PUZZLE_CATEGORY_IDS.items():
        platform_app_ids: list[str] = []
        seen_app_ids: set[str] = set()

        for category_id in category_ids:
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

        install_map = _fetch_install_totals(
            platform=platform,
            app_ids=platform_app_ids,
            start_date=release_start_date,
            end_date=install_end_date,
            auth_token=config.sensor_tower_api_key,
        )
        if not install_map:
            logger.warning("No install data found for platform=%s.", platform)
            continue

        surviving_ids: list[str] = []
        for app_id, install_data in install_map.items():
            installs = int(install_data.get("installs_last_day", 0) or 0)
            if installs < min_installs:
                continue
            if max_installs is not None and installs > max_installs:
                continue
            surviving_ids.append(app_id)

        if not surviving_ids:
            logger.info(
                "No apps met the install threshold for platform=%s min_installs=%s.",
                platform,
                min_installs,
            )
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
                    launch_date = datetime.fromisoformat(
                        str(launch_raw).split("T")[0]
                    ).date()
                    if launch_date < cutoff_date:
                        logger.debug(
                            "Skipping %s — launch_date %s is older than cutoff %s",
                            game_data.get("name"),
                            launch_date,
                            cutoff_date,
                        )
                        continue
                except ValueError:
                    pass

            results.append(game_data)

    return results
