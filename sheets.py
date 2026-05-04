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


def _build_row(game: dict[str, Any]) -> list[str]:
    """Build a sheet row from a game payload."""
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


def write_to_sheet(games: list[dict[str, Any]]) -> str | None:
    """Write today's games to a new tab in the Google Sheet.

    Returns the sheet URL on success, None on failure.
    Tab name = today's date in YYYY-MM-DD format.
    Columns: Game Name | Developer | Platform | Country | Release Date | Installs | Store URL
    If a tab with today's date already exists, append to it.
    Loads credentials from GOOGLE_SHEETS_CREDENTIALS env var (JSON string).
    Loads sheet ID from GOOGLE_SHEET_ID env var.
    Returns None and logs error on any failure — never crashes.
    """
    if not games:
        logger.info("No games to write to Google Sheets.")
        return None

    credentials_raw = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "").strip()
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if not credentials_raw or not sheet_id:
        logger.error(
            "Missing Google Sheets configuration. GOOGLE_SHEETS_CREDENTIALS or GOOGLE_SHEET_ID is not set."
        )
        return None

    try:
        credentials_info = json.loads(credentials_raw)
        credentials = Credentials.from_service_account_info(
            credentials_info,
            scopes=SCOPES,
        )
        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_key(sheet_id)

        tab_name = datetime.utcnow().strftime("%Y-%m-%d")
        headers = [
            "Game Name",
            "Developer",
            "Platform",
            "Country",
            "Release Date",
            "Installs",
            "Store URL",
        ]

        try:
            worksheet = spreadsheet.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=tab_name,
                rows=max(len(games) + 10, 100),
                cols=len(headers),
            )

        existing_values = worksheet.get_all_values()
        if not existing_values:
            worksheet.append_row(headers, value_input_option="RAW")

        rows = [_build_row(game) for game in games]
        worksheet.append_rows(rows, value_input_option="RAW")
        return spreadsheet.url
    except Exception as exc:
        logger.error("Failed to write games to Google Sheets: %s", exc)
        return None
