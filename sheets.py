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
            "Missing Google Sheets configuration. GOOGLE_SHEETS_CREDENTIALS or GOOGLE_SHEET_ID is not set."
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


def _build_row(item: dict[str, Any]) -> list[str]:
    """Build a sheet row from a scored game payload."""
    game = item["game"]
    launch_date = str(game.get("launch_date") or "").strip()
    if "T" in launch_date:
        launch_date = launch_date.split("T")[0]

    installs = game.get("installs_last_day", 0)
    try:
        installs_text = str(int(installs or 0))
    except (TypeError, ValueError):
        installs_text = "0"

    return [
        str(game.get("name") or ""),
        str(game.get("publisher") or ""),
        str(game.get("platform") or ""),
        str(game.get("country") or ""),
        launch_date,
        installs_text,
        str(item.get("score", 0)),
        str(item.get("mechanic", "")),
        str(game.get("store_url") or ""),
    ]


def _build_all_games_row(game: dict[str, Any]) -> list[str]:
    """Build a sheet row for the all-games export."""
    launch_date = str(game.get("launch_date") or "").strip()
    if "T" in launch_date:
        launch_date = launch_date.split("T")[0]

    installs = game.get("installs_last_day", 0)
    try:
        installs_text = str(int(installs or 0))
    except (TypeError, ValueError):
        installs_text = "0"

    return [
        str(game.get("name") or ""),
        str(game.get("publisher") or ""),
        str(game.get("platform") or ""),
        str(game.get("country") or ""),
        launch_date,
        installs_text,
        str(game.get("store_url") or ""),
    ]


def write_to_sheet(scored_games: list[dict[str, Any]]) -> str | None:
    """Write relevant games to 'Relevant - YYYY-MM-DD' tab in the Google Sheet.

    Returns the sheet URL on success, None on failure.
    Columns: Game Name | Developer | Platform | Country | Release Date | Installs | Relevance Score | Mechanic | Store URL
    If a tab with today's date already exists, append to it.
    Loads credentials from GOOGLE_SHEETS_CREDENTIALS env var (JSON string).
    Loads sheet ID from GOOGLE_SHEET_ID env var.
    Returns None and logs error on any failure — never crashes.
    """
    if not scored_games:
        logger.info("No games to write to Google Sheets.")
        return None

    try:
        spreadsheet = _load_spreadsheet()
        tab_name = f"Relevant - {datetime.utcnow().strftime('%Y-%m-%d')}"
        headers = [
            "Game Name",
            "Developer",
            "Platform",
            "Country",
            "Release Date",
            "Installs",
            "Relevance Score",
            "Mechanic",
            "Store URL",
        ]
        worksheet = _get_or_create_worksheet(
            spreadsheet=spreadsheet,
            tab_name=tab_name,
            rows=len(scored_games) + 10,
            cols=len(headers),
        )
        _ensure_headers(worksheet, headers)

        sorted_games = sorted(
            scored_games,
            key=lambda item: int(item.get("score", 0)),
            reverse=True,
        )
        rows = [_build_row(item) for item in sorted_games]
        worksheet.append_rows(rows, value_input_option="RAW")
        return spreadsheet.url
    except Exception as exc:
        logger.error("Failed to write relevant games to Google Sheets: %s", exc)
        return None


def write_all_games_to_sheet(games: list[dict[str, Any]]) -> None:
    """Write ALL fetched games (no relevance filter) to 'All Games - YYYY-MM-DD' tab.

    Columns: Game Name | Developer | Platform | Country | Release Date | Installs | Store URL
    Sorted by installs descending.
    Same credential loading as write_to_sheet.
    Never crashes — logs errors.
    """
    if not games:
        logger.info("No fetched games to write to all-games sheet.")
        return

    try:
        spreadsheet = _load_spreadsheet()
        tab_name = f"All Games - {datetime.utcnow().strftime('%Y-%m-%d')}"
        headers = [
            "Game Name",
            "Developer",
            "Platform",
            "Country",
            "Release Date",
            "Installs",
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
            key=lambda game: int(game.get("installs_last_day", 0) or 0),
            reverse=True,
        )
        rows = [_build_all_games_row(game) for game in sorted_games]
        worksheet.append_rows(rows, value_input_option="RAW")
    except Exception as exc:
        logger.error("Failed to write all games to Google Sheets: %s", exc)
