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
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sensortower.com"
RATE_LIMIT_DELAY = 0.2
REQUEST_TIMEOUT = 180
APP_TAG_PAGE_LIMIT = 2000
SUB_GENRE_WORKERS = 3
MANUAL_RETRIES = 3
RETRY_BACKOFF_BASE = 5.0
FILTER_CACHE_PATH = Path(".sub_genre_filter_cache.json")

_filter_cache: dict[str, str] | None = None
_filter_cache_lock = threading.Lock()


def _build_session() -> requests.Session:
    """Persistent session with retry adapter for transient HTTP errors."""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        backoff_factor=2.0,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=20,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_session = _build_session()


def _request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = REQUEST_TIMEOUT,
    label: str = "",
) -> requests.Response | None:
    """Make a request, manually retrying on read/connection timeouts.

    The HTTPAdapter retry strategy handles HTTP status codes but does NOT retry
    ReadTimeout / ConnectionError raised before a response arrives. This wrapper
    fills that gap.
    """
    last_exc: Exception | None = None
    for attempt in range(1, MANUAL_RETRIES + 1):
        try:
            response = _session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=timeout,
            )
            return response
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            if attempt < MANUAL_RETRIES:
                wait = RETRY_BACKOFF_BASE * attempt
                logger.info(
                    "Retry %d/%d after %.1fs (%s): %s",
                    attempt, MANUAL_RETRIES, wait, label or url, exc.__class__.__name__,
                )
                time.sleep(wait)
            else:
                logger.warning(
                    "Gave up after %d retries (%s): %s",
                    MANUAL_RETRIES, label or url, exc,
                )
    if last_exc:
        return None
    return None

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


def _load_filter_cache() -> dict[str, str]:
    global _filter_cache
    with _filter_cache_lock:
        if _filter_cache is not None:
            return _filter_cache
        if FILTER_CACHE_PATH.exists():
            try:
                _filter_cache = json.loads(FILTER_CACHE_PATH.read_text())
                if not isinstance(_filter_cache, dict):
                    _filter_cache = {}
            except (json.JSONDecodeError, OSError):
                _filter_cache = {}
        else:
            _filter_cache = {}
        return _filter_cache


def _save_filter_cache() -> None:
    with _filter_cache_lock:
        if _filter_cache is None:
            return
        try:
            FILTER_CACHE_PATH.write_text(json.dumps(_filter_cache, indent=2))
        except OSError as exc:
            logger.debug("Filter cache save failed: %s", exc)


# ---------------------------------------------------------------------------
# 1. Discover sub-genre values dynamically
# ---------------------------------------------------------------------------

def _discover_sub_genre_values(auth_token: str) -> list[str]:
    """Fetch ALL valid 'Game Sub-genre' values from the custom fields metadata.

    Endpoint: GET /v1/custom_fields_filter/fields_values
    Returns the full discovered list (no priority filtering) ordered so priority
    sub-genres run first, with the rest appended. Falls back to FALLBACK_SUB_GENRES
    on failure.
    """
    url = f"{BASE_URL}/v1/custom_fields_filter/fields_values"
    time.sleep(RATE_LIMIT_DELAY)
    response = _request_with_retry(
        "GET",
        url,
        headers=_auth_headers(auth_token),
        params={"term": "Game Sub-genre"},
        timeout=60,
        label="fields_values",
    )
    if response is None or response.status_code != 200:
        status = response.status_code if response is not None else "no-response"
        logger.info("fields_values returned status=%s, using fallback list", status)
        return list(FALLBACK_SUB_GENRES)

    try:
        data = response.json()
    except ValueError:
        logger.info("fields_values returned non-JSON, using fallback list")
        return list(FALLBACK_SUB_GENRES)

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
                api_values = [str(v) for v in values if v]
                priority = [sg for sg in PRIORITY_SUB_GENRES if sg in set(api_values)]
                priority_set = set(priority)
                rest = [sg for sg in api_values if sg not in priority_set]
                ordered = priority + rest
                logger.info(
                    "Discovered %d sub-genre values from API (running ALL, priority first)",
                    len(ordered),
                )
                return ordered

    logger.info("Could not extract sub-genre values from response, using fallback")
    return list(FALLBACK_SUB_GENRES)


# ---------------------------------------------------------------------------
# 2. Create a custom fields filter for a single sub-genre
# ---------------------------------------------------------------------------

def _create_filter(sub_genre: str, auth_token: str) -> str | None:
    """POST /v1/custom_fields_filter — returns filter ID (cached to disk)."""
    cache = _load_filter_cache()
    cached_id = cache.get(sub_genre)
    if cached_id:
        return cached_id

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
    time.sleep(RATE_LIMIT_DELAY)
    response = _request_with_retry(
        "POST",
        url,
        headers={**_auth_headers(auth_token), "Content-Type": "application/json"},
        json_body=body,
        timeout=60,
        label=f"filter_create[{sub_genre}]",
    )
    if response is None or response.status_code != 200:
        if response is not None:
            logger.debug(
                "Filter create '%s' status=%d body=%s",
                sub_genre, response.status_code, response.text[:200],
            )
        return None
    try:
        filter_id = response.json().get("custom_fields_filter_id")
    except ValueError:
        return None
    if filter_id:
        with _filter_cache_lock:
            cache[sub_genre] = filter_id
    return filter_id


# ---------------------------------------------------------------------------
# 3. Fetch ALL apps matching a filter via /v1/app_tag/apps
# ---------------------------------------------------------------------------

def _fetch_app_tag_for_type(
    filter_id: str,
    auth_token: str,
    target_set: set[str],
    app_id_type: str,
    sub_genre: str = "",
) -> set[str]:
    """Fetch one endpoint type (itunes or unified) and return target matches.

    Paginates fully — no artificial page cap — so that small / newly-released
    games appearing on later pages are still discovered.
    """
    found: set[str] = set()
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

        time.sleep(RATE_LIMIT_DELAY)
        response = _request_with_retry(
            "GET",
            url,
            headers=_auth_headers(auth_token),
            params=params,
            timeout=REQUEST_TIMEOUT,
            label=f"app_tag[{sub_genre}/{app_id_type}/p{pages_fetched + 1}]",
        )
        if response is None:
            logger.warning(
                "app_tag '%s' [%s] page %d: gave up after retries",
                sub_genre, app_id_type, pages_fetched + 1,
            )
            break
        if response.status_code != 200:
            logger.info(
                "app_tag %s [%s] status=%d body=%s",
                sub_genre, app_id_type, response.status_code, response.text[:300],
            )
            break

        try:
            data = response.json()
        except ValueError:
            logger.info("app_tag %s [%s] returned non-JSON", sub_genre, app_id_type)
            break

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
        if not new_last or new_last == last_known_id or not page_ids:
            break
        last_known_id = new_last

    return found


def _find_matches_in_app_tag(
    filter_id: str,
    auth_token: str,
    target_set: set[str],
    sub_genre: str = "",
) -> set[str]:
    """Run itunes + unified endpoints in parallel and merge target matches.

    Splits target_set by ID shape: numeric (iOS) → itunes only,
    non-numeric (Android package names) → unified only.
    """
    numeric_targets = {aid for aid in target_set if aid.isdigit()}
    package_targets = target_set - numeric_targets

    to_run: list[tuple[str, set[str]]] = []
    if numeric_targets:
        to_run.append(("itunes", numeric_targets))
    if package_targets:
        to_run.append(("unified", package_targets))

    if not to_run:
        return set()

    if len(to_run) == 1:
        app_id_type, subset = to_run[0]
        return _fetch_app_tag_for_type(filter_id, auth_token, subset, app_id_type, sub_genre)

    found: set[str] = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(
                _fetch_app_tag_for_type, filter_id, auth_token, subset, app_id_type, sub_genre,
            ): app_id_type
            for app_id_type, subset in to_run
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                found.update(future.result())
            except Exception as exc:
                logger.info("app_tag parallel fetch failed %s: %s", sub_genre, exc)

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
    remaining_lock = threading.Lock()

    def _check_sub_genre(sub_genre: str) -> tuple[str, set[str]]:
        with remaining_lock:
            current_remaining = set(remaining)
        if not current_remaining:
            return sub_genre, set()
        filter_id = _create_filter(sub_genre, auth_token)
        if not filter_id:
            return sub_genre, set()
        matched = _find_matches_in_app_tag(filter_id, auth_token, current_remaining, sub_genre)
        return sub_genre, matched

    with concurrent.futures.ThreadPoolExecutor(max_workers=SUB_GENRE_WORKERS) as executor:
        batch_size = SUB_GENRE_WORKERS
        for batch_start in range(0, len(sub_genres), batch_size):
            if not remaining:
                break

            batch = sub_genres[batch_start:batch_start + batch_size]
            futures = {
                executor.submit(_check_sub_genre, sg): sg for sg in batch
            }

            for future in concurrent.futures.as_completed(futures):
                sub_genre, matched_ids = future.result()
                with remaining_lock:
                    new_matches = matched_ids & remaining
                    for app_id in new_matches:
                        result[app_id] = sub_genre
                        remaining.discard(app_id)
                if matched_ids:
                    logger.info("Sub-genre '%s': %d matches", sub_genre, len(matched_ids))

            if not remaining:
                logger.info("All target apps matched, stopping early")
                break

    _save_filter_cache()
    logger.info("Sub-genre mapping complete: %d/%d apps matched", len(result), len(target_set))
    return result
