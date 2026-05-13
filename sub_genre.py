"""Fetch Game Sub-genre labels via the official Sensor Tower Custom Fields API.

Uses auth_token (query param) — no session cookie needed.

Strategy:
  1. Discover available sub-genre values via /v1/custom_fields_filter/fields_values
     (falls back to a hardcoded list if the endpoint is inaccessible).
  2. For each sub-genre, create a filter via POST /v1/custom_fields_filter.
  3. Query /v1/app_tag/apps (NOT /v1/{os}/ranking) to get ALL apps matching
     the filter — including small / newly released games that never appear on
     top charts.
  4. Match returned app IDs against the target list.

Public API:
    get_sub_genres_for_apps(app_ids, auth_token) -> dict[str, str]
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sensortower.com"
RATE_LIMIT_DELAY = 0.3
APP_TAG_PAGE_LIMIT = 2000

FALLBACK_SUB_GENRES = [
    "Word", "Block", "Bubble Shooter", "Solitaire", "Hidden Objects",
    "Trivia", "Board", "Card", "Jigsaw", "Tower Defense",
    "Match Swap", "Match Blast", "Match Chain", "Match Pair", "Match Merge",
    "Physics", "Mahjong", "Maze", "Sort", "Interactive Story",
    "Puzzle RPG", "Sandbox",
]

PRIORITY_SUB_GENRES = [
    "Match Swap", "Match Blast", "Match Chain", "Match Pair", "Match Merge",
    "Word", "Bubble Shooter", "Solitaire", "Block", "Sort",
    "Jigsaw", "Trivia", "Board", "Card", "Hidden Objects",
    "Maze", "Physics", "Mahjong", "Tower Defense", "Puzzle RPG",
    "Match Merge 2", "Match Merge 3", "Numbers", "Screw", "Riddle",
    "Other Puzzle", "Real-Time Puzzle", "Environmental",
    "Ultracasual", "Interactive Story", "Sandbox",
    "Idler", "Simulator", "Time Management", "Adventure",
    "Platformer / Runner", "Tycoon / Crafting",
    "Solitaire / Mahjong", "Drawing & Coloring",
    "Virtual Pet", "Lifestyle Simulator", "Customization",
]


def _auth_headers(auth_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {auth_token}",
        "Accept": "application/json",
    }


# ---------------------------------------------------------------------------
# 1. Discover sub-genre values dynamically
# ---------------------------------------------------------------------------

def _discover_sub_genre_values(auth_token: str) -> list[str]:
    """Fetch valid 'Game Sub-genre' values from the custom fields metadata.

    Endpoint: GET /v1/custom_fields_filter/fields_values
    Falls back to FALLBACK_SUB_GENRES on any failure.
    """
    url = f"{BASE_URL}/v1/custom_fields_filter/fields_values"
    try:
        time.sleep(RATE_LIMIT_DELAY)
        response = requests.get(
            url,
            params={"term": "Game Sub-genre"},
            headers=_auth_headers(auth_token),
            timeout=30,
        )
        if response.status_code != 200:
            logger.info(
                "fields_values endpoint returned status=%d, using fallback list",
                response.status_code,
            )
            return list(FALLBACK_SUB_GENRES)

        data = response.json()
        custom_fields = data.get("custom_fields") if isinstance(data, dict) else None
        if not custom_fields:
            custom_fields = data if isinstance(data, list) else []
        if isinstance(data, dict) and not custom_fields:
            custom_fields = data.get("data") or data.get("fields") or []

        for field in (custom_fields if isinstance(custom_fields, list) else []):
            if not isinstance(field, dict):
                continue
            field_name = field.get("name") or field.get("field_name") or ""
            if "sub-genre" in field_name.lower() or "sub_genre" in field_name.lower():
                values = field.get("values") or field.get("possible_values") or []
                if values and isinstance(values, list):
                    api_values = set(str(v) for v in values if v)
                    ordered = [sg for sg in PRIORITY_SUB_GENRES if sg in api_values]
                    logger.info(
                        "Discovered %d sub-genre values from API, using %d priority matches",
                        len(api_values), len(ordered),
                    )
                    return ordered if ordered else [str(v) for v in values if v]

        logger.info("Could not extract sub-genre values from response, using fallback")
        return list(FALLBACK_SUB_GENRES)

    except Exception as exc:
        logger.info("fields_values request failed (%s), using fallback list", exc)
        return list(FALLBACK_SUB_GENRES)


# ---------------------------------------------------------------------------
# 2. Create a custom fields filter for a single sub-genre
# ---------------------------------------------------------------------------

def _create_filter(sub_genre: str, auth_token: str) -> str | None:
    """POST /v1/custom_fields_filter — returns filter ID."""
    url = f"{BASE_URL}/v1/custom_fields_filter"
    body = {
        "custom_fields": [
            {
                "name": "Game Sub-genre",
                "values": [sub_genre],
                "global": True,
                "exclude": False,
            }
        ]
    }
    try:
        time.sleep(RATE_LIMIT_DELAY)
        response = requests.post(
            url,
            headers={**_auth_headers(auth_token), "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        if response.status_code != 200:
            logger.debug("Filter create '%s' status=%d body=%s", sub_genre, response.status_code, response.text[:200])
            return None
        filter_id = response.json().get("custom_fields_filter_id")
        return filter_id
    except Exception as exc:
        logger.info("Filter create failed for '%s': %s", sub_genre, exc)
    return None


# ---------------------------------------------------------------------------
# 3. Fetch ALL apps matching a filter via /v1/app_tag/apps
# ---------------------------------------------------------------------------

def _find_matches_in_app_tag(
    filter_id: str,
    auth_token: str,
    target_set: set[str],
) -> set[str]:
    """GET /v1/app_tag/apps — check which target IDs exist in the filtered results.

    Unlike /v1/{os}/ranking, this endpoint returns ALL apps matching the filter,
    including small / newly released games. Checks itunes (flat ID list, fast)
    and unified (includes android_app_ids) endpoints. Returns only the IDs from
    target_set that were found.
    """
    found: set[str] = set()

    for app_id_type in ("itunes", "unified"):
        last_known_id: str | None = None
        pages_fetched = 0

        while True:
            url = f"{BASE_URL}/v1/app_tag/apps"
            params: dict[str, Any] = {
                "app_id_type": app_id_type,
                "custom_fields_filter_id": filter_id,
            }
            if last_known_id:
                params["last_known_id"] = last_known_id

            try:
                time.sleep(RATE_LIMIT_DELAY)
                response = requests.get(
                    url,
                    params=params,
                    headers=_auth_headers(auth_token),
                    timeout=60,
                )
                if response.status_code != 200:
                    logger.info(
                        "app_tag %s status=%d body=%s",
                        app_id_type, response.status_code, response.text[:300],
                    )
                    break

                data = response.json()
                page_ids: set[str] = set()

                if isinstance(data, dict):
                    flat_ids = data.get("app_ids")
                    if isinstance(flat_ids, list) and flat_ids:
                        page_ids = {str(aid) for aid in flat_ids if aid}
                    else:
                        entries = data.get("data") or data.get("apps") or data.get("results") or []
                        for entry in entries:
                            if not isinstance(entry, dict):
                                page_ids.add(str(entry))
                                continue
                            for id_key in ("itunes_app_ids", "android_app_ids"):
                                id_list = entry.get(id_key)
                                if isinstance(id_list, list):
                                    page_ids.update(str(aid) for aid in id_list if aid)
                            unified_id = entry.get("unified_app_id") or entry.get("app_id") or entry.get("id")
                            if unified_id and not entry.get("itunes_app_ids") and not entry.get("android_app_ids"):
                                page_ids.add(str(unified_id))

                    new_last = data.get("last_known_id")
                elif isinstance(data, list):
                    page_ids = {str(aid) for aid in data if aid}
                    new_last = None
                else:
                    new_last = None

                matches_on_page = page_ids & target_set
                found.update(matches_on_page)

                if found == target_set:
                    return found

                pages_fetched += 1
                if not new_last or new_last == last_known_id or pages_fetched >= 3:
                    break
                last_known_id = new_last

            except Exception as exc:
                logger.info("app_tag fetch failed %s: %s", app_id_type, exc)
                break

    return found


# ---------------------------------------------------------------------------
# 4. Public API: map target app IDs -> sub-genre names
# ---------------------------------------------------------------------------

def get_sub_genres_for_apps(
    target_app_ids: list[str],
    auth_token: str,
) -> dict[str, str]:
    """Map app IDs to their Game Sub-genre via the Custom Fields + App Tag API.

    Returns {app_id: sub_genre_name} for matched apps.
    """
    target_set = set(str(aid) for aid in target_app_ids)
    result: dict[str, str] = {}

    sub_genres = _discover_sub_genre_values(auth_token)
    logger.info(
        "Matching %d apps against %d sub-genres",
        len(target_set), len(sub_genres),
    )

    remaining = set(target_set)

    def _check_sub_genre(sub_genre: str) -> tuple[str, set[str]]:
        filter_id = _create_filter(sub_genre, auth_token)
        if not filter_id:
            return sub_genre, set()
        matched = _find_matches_in_app_tag(filter_id, auth_token, remaining)
        return sub_genre, matched

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        batch_size = 3
        for batch_start in range(0, len(sub_genres), batch_size):
            if not remaining:
                break

            batch = sub_genres[batch_start:batch_start + batch_size]
            futures = {
                executor.submit(_check_sub_genre, sg): sg for sg in batch
            }

            for future in concurrent.futures.as_completed(futures):
                sub_genre, matched_ids = future.result()
                for app_id in matched_ids:
                    if app_id in remaining:
                        result[app_id] = sub_genre
                        remaining.discard(app_id)
                if matched_ids:
                    logger.info("Sub-genre '%s': %d matches", sub_genre, len(matched_ids))

            if not remaining:
                logger.info("All target apps matched, stopping early")
                break

    logger.info("Sub-genre mapping complete: %d/%d apps matched", len(result), len(target_set))
    return result
