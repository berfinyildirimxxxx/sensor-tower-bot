"""Google Sheets export — daily scanned + new-radar tabs."""

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

SCANNED_HEADERS = [
    "Game Name", "Developer", "Platform", "Country",
    "Release Date", "Total Installs", "Genre", "Sub-genre", "Store URL",
]

NEW_RADAR_HEADERS = [
    "Game Name", "Developer", "Platform", "Country",
    "Release Date", "Total Installs", "Genre", "Sub-genre", "Store URL",
]


def _load_spreadsheet() -> gspread.Spreadsheet:
    credentials_raw = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "").strip()
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if not credentials_raw or not sheet_id:
        raise RuntimeError(
            "Missing GOOGLE_SHEETS_CREDENTIALS or GOOGLE_SHEET_ID env var."
        )
    credentials_info = json.loads(credentials_raw)
    credentials = Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
    client = gspread.authorize(credentials)
    return client.open_by_key(sheet_id)


def _get_or_create_worksheet(
    spreadsheet: gspread.Spreadsheet, tab_name: str, rows: int, cols: int
) -> gspread.Worksheet:
    try:
        return spreadsheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=tab_name, rows=max(rows, 100), cols=cols)


def _ensure_headers(worksheet: gspread.Worksheet, headers: list[str]) -> None:
    if not worksheet.get_all_values():
        worksheet.append_row(headers, value_input_option="RAW")


def _get_installs(game: dict[str, Any]) -> int:
    val = game.get("installs_total") or game.get("installs") or 0
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _format_launch_date(game: dict[str, Any]) -> str:
    d = str(game.get("launch_date") or "").strip()
    return d.split("T")[0] if "T" in d else d


def _build_row(game: dict[str, Any]) -> list[str]:
    return [
        str(game.get("name") or ""),
        str(game.get("publisher") or ""),
        str(game.get("platform") or "").upper(),
        str(game.get("country") or ""),
        _format_launch_date(game),
        str(_get_installs(game)),
        str(game.get("st_genre") or game.get("intel_category") or game.get("category") or ""),
        str(game.get("st_sub_genre") or ""),
        str(game.get("store_url") or ""),
    ]


def write_all_games_to_sheet(games: list[dict[str, Any]]) -> None:
    """Write all fetched games to 'Scanned - YYYY-MM-DD' tab."""
    if not games:
        logger.info("No games to write to scanned tab.")
        return
    try:
        spreadsheet = _load_spreadsheet()
        tab_name = f"Scanned - {datetime.utcnow().strftime('%Y-%m-%d')}"
        ws = _get_or_create_worksheet(spreadsheet, tab_name, len(games) + 10, len(SCANNED_HEADERS))
        _ensure_headers(ws, SCANNED_HEADERS)
        sorted_games = sorted(games, key=_get_installs, reverse=True)
        ws.append_rows([_build_row(g) for g in sorted_games], value_input_option="RAW")
        logger.info("Wrote %d games to sheet tab '%s'.", len(sorted_games), tab_name)
    except Exception as exc:
        logger.error("Failed to write scanned tab: %s", exc)


def write_new_games_to_sheet(games: list[dict[str, Any]]) -> None:
    """Write today's new radar additions to 'New Radar - YYYY-MM-DD' tab."""
    if not games:
        logger.info("No new radar games to write.")
        return
    try:
        spreadsheet = _load_spreadsheet()
        tab_name = f"New Radar - {datetime.utcnow().strftime('%Y-%m-%d')}"
        ws = _get_or_create_worksheet(spreadsheet, tab_name, len(games) + 10, len(NEW_RADAR_HEADERS))
        _ensure_headers(ws, NEW_RADAR_HEADERS)
        sorted_games = sorted(games, key=_get_installs, reverse=True)
        ws.append_rows([_build_row(g) for g in sorted_games], value_input_option="RAW")
        logger.info("Wrote %d new-radar games to sheet tab '%s'.", len(sorted_games), tab_name)
    except Exception as exc:
        logger.error("Failed to write new-radar tab: %s", exc)
