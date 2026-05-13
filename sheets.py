"""Google Sheets export helpers for daily bot runs."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import os
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _load_spreadsheet() -> gspread.Spreadsheet:
    """Load the configured Google Spreadsheet."""
    credentials_raw = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "").strip()
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if not credentials_raw or not sheet_id:
        raise RuntimeError(
            "Missing Google Sheets configuration. "
            "GOOGLE_SHEETS_CREDENTIALS or GOOGLE_SHEET_ID is not set."
        )

    credentials_info = json.loads(credentials_raw)
    credentials = Credentials.from_service_account_info(
        credentials_info,
        scopes=SCOPES,
    )
    client = gspread.authorize(credentials)
    return client.open_by_key(sheet_id)


def _get_or_create_worksheet(
    spreadsheet: gspread.Spreadsheet,
    tab_name: str,
    rows: int,
    cols: int,
) -> gspread.Worksheet:
    """Return an existing worksheet by name or create it if missing."""
    try:
        return spreadsheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(
            title=tab_name,
            rows=max(rows, 100),
            cols=cols,
        )


def _ensure_headers(worksheet: gspread.Worksheet, headers: list[str]) -> None:
    """Write header row only when the worksheet is empty."""
    if not worksheet.get_all_values():
        worksheet.append_row(headers, value_input_option="RAW")


def _get_installs(game: dict[str, Any]) -> int:
    """Get total installs from game payload, handling all key names."""
    val = (
        game.get("installs")
        or game.get("installs_total")
        or game.get("installs_last_day")
        or 0
    )
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _format_launch_date(game: dict[str, Any]) -> str:
    """Extract and format the launch date as YYYY-MM-DD."""
    launch_date = str(game.get("launch_date") or "").strip()
    if "T" in launch_date:
        return launch_date.split("T")[0]
    return launch_date


def _build_relevant_row(item: dict[str, Any]) -> list[str]:
    """Build a sheet row from a scored game (flat format)."""
    installs = _get_installs(item)
    launch_date = _format_launch_date(item)

    return [
        str(item.get("name") or ""),
        str(item.get("publisher") or ""),
        str(item.get("platform") or "").upper(),
        str(item.get("country") or ""),
        launch_date,
        str(installs),
        str(item.get("score", 0)),
        str(item.get("mechanic", "")),
        str(item.get("reason", "")),
        str(item.get("store_url") or ""),
    ]


def _build_all_games_row(game: dict[str, Any]) -> list[str]:
    """Build a sheet row for the all-games export with sub-genre."""
    installs = _get_installs(game)
    launch_date = _format_launch_date(game)

    return [
        str(game.get("name") or ""),
        str(game.get("publisher") or ""),
        str(game.get("platform") or "").upper(),
        str(game.get("country") or ""),
        launch_date,
        str(installs),
        str(game.get("category") or ""),
        str(game.get("intel_sub_genre") or ""),
        str(game.get("store_url") or ""),
    ]


def write_to_sheet(scored_games: list[dict[str, Any]]) -> str | None:
    """Write portfolio-match games to 'Portfolio Match - YYYY-MM-DD' tab.

    Returns the sheet URL on success, None on failure.
    """
    if not scored_games:
        logger.info("No portfolio-match games to write to Google Sheets.")
        return None

    try:
        spreadsheet = _load_spreadsheet()
        tab_name = f"Radar Game Info {datetime.utcnow().strftime('%d.%m.%Y')}"
        headers = [
            "Game Name",
            "Developer",
            "Platform",
            "Country",
            "Release Date",
            "Total Installs",
            "Score",
            "Mechanic",
            "Reason",
            "Store URL",
        ]
        worksheet = _get_or_create_worksheet(
            spreadsheet=spreadsheet,
            tab_name=tab_name,
            rows=len(scored_games) + 10,
            cols=len(headers),
        )
        _ensure_headers(worksheet, headers)

        # Sort by installs descending (highest installs first)
        sorted_games = sorted(
            scored_games,
            key=lambda item: _get_installs(item),
            reverse=True,
        )
        rows = [_build_relevant_row(item) for item in sorted_games]
        worksheet.append_rows(rows, value_input_option="RAW")
        logger.info("Wrote %d portfolio-match games to sheet tab '%s'.", len(rows), tab_name)
        return spreadsheet.url
    except Exception as exc:
        logger.error("Failed to write portfolio-match games to Google Sheets: %s", exc)
        return None


def write_all_games_to_sheet(games: list[dict[str, Any]]) -> None:
    """Write ALL fetched games (iOS + Android, no filter) to 'Scanned - YYYY-MM-DD' tab.

    Sorted by total installs descending. Never crashes — logs errors.
    """
    if not games:
        logger.info("No fetched games to write to scanned-games sheet.")
        return

    try:
        spreadsheet = _load_spreadsheet()
        tab_name = f"Radar Game Info {datetime.utcnow().strftime('%d.%m.%Y')}"
        headers = [
            "Game Name",
            "Developer",
            "Platform",
            "Country",
            "Release Date",
            "Total Installs",
            "Category",
            "Sub-Genre",
            "Store URL",
        ]
        worksheet = _get_or_create_worksheet(
            spreadsheet=spreadsheet,
            tab_name=tab_name,
            rows=len(games) + 10,
            cols=len(headers),
        )
        _ensure_headers(worksheet, headers)

        sorted_games = sorted(
            games,
            key=lambda game: _get_installs(game),
            reverse=True,
        )
        rows = [_build_all_games_row(game) for game in sorted_games]
        worksheet.append_rows(rows, value_input_option="RAW")
        logger.info(
            "Wrote %d total scanned games to sheet tab '%s'.", len(rows), tab_name
        )
    except Exception as exc:
        logger.error("Failed to write scanned games to Google Sheets: %s", exc)
