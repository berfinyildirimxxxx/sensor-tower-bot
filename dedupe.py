"""Deduplication helpers for sent game alerts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _resolve_path(path: str) -> Path:
    """Resolve a registry path relative to this file when needed."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return Path(__file__).resolve().parent / candidate


def _empty_registry() -> dict[str, dict[str, Any]]:
    """Return a fresh empty registry structure."""
    return {"sent": {}}


def _normalize_store_url(value: Any) -> str:
    """Normalize a store URL for duplicate comparisons."""
    return str(value or "").strip().lower()


def _normalize_identifier(value: Any) -> str:
    """Normalize an identifier-like value for duplicate comparisons."""
    return str(value or "").strip()


def _parse_sent_at(value: Any) -> datetime | None:
    """Parse an ISO 8601 UTC timestamp from the registry."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Skipping registry entry with invalid sent_at timestamp: %s", text)
        return None


def _registry_sent_map(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the mutable sent-entry map, creating it if necessary."""
    sent = registry.get("sent")
    if not isinstance(sent, dict):
        sent = {}
        registry["sent"] = sent
    return sent


def load_sent_games(path: str = "sent_games.json") -> dict[str, Any]:
    """Load the sent games registry. Return {"sent": {}} if file missing or invalid JSON."""
    resolved_path = _resolve_path(path)
    if not resolved_path.exists():
        return _empty_registry()

    try:
        with resolved_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return _empty_registry()
    except json.JSONDecodeError as exc:
        logger.warning("Sent games registry is invalid JSON at %s: %s", resolved_path, exc)
        return _empty_registry()
    except OSError as exc:
        logger.warning("Unable to read sent games registry at %s: %s", resolved_path, exc)
        return _empty_registry()

    if not isinstance(data, dict):
        logger.warning("Sent games registry has unexpected shape at %s.", resolved_path)
        return _empty_registry()

    sent = data.get("sent")
    if not isinstance(sent, dict):
        data["sent"] = {}

    return data


def save_sent_games(data: dict[str, Any], path: str = "sent_games.json") -> None:
    """Save back to disk. Pretty-printed JSON (indent=2). Create file if missing."""
    resolved_path = _resolve_path(path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with resolved_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except OSError as exc:
        logger.error("Unable to save sent games registry at %s: %s", resolved_path, exc)


def is_already_sent(game: dict[str, Any], registry: dict[str, Any] | None = None) -> bool:
    """Check if the game already exists in the registry by fid, app_id, or store_url."""
    active_registry = registry if registry is not None else load_sent_games()
    sent_entries = _registry_sent_map(active_registry)

    game_fid = _normalize_identifier(game.get("fid"))
    game_app_id = _normalize_identifier(game.get("app_id"))
    game_store_url = _normalize_store_url(game.get("store_url"))

    for entry in sent_entries.values():
        if not isinstance(entry, dict):
            continue

        entry_fid = _normalize_identifier(entry.get("fid"))
        entry_app_id = _normalize_identifier(entry.get("app_id"))
        entry_store_url = _normalize_store_url(entry.get("store_url"))

        if game_fid and entry_fid and game_fid == entry_fid:
            return True
        if game_app_id and entry_app_id and game_app_id == entry_app_id:
            return True
        if game_store_url and entry_store_url and game_store_url == entry_store_url:
            return True

    return False


def mark_as_sent(
    game: dict[str, Any],
    registry: dict[str, Any] | None = None,
    path: str = "sent_games.json",
) -> None:
    """Add the game to the registry with current UTC timestamp."""
    active_registry = registry if registry is not None else load_sent_games(path)
    sent_entries = _registry_sent_map(active_registry)

    fid = _normalize_identifier(game.get("fid"))
    app_id = _normalize_identifier(game.get("app_id"))
    store_url = str(game.get("store_url") or "").strip()
    unique_key = (
        fid
        or app_id
        or _normalize_store_url(store_url)
        or datetime.utcnow().isoformat()
    )

    sent_entries[unique_key] = {
        "name": str(game.get("name") or ""),
        "fid": fid,
        "app_id": app_id,
        "store_url": store_url,
        "platform": str(game.get("platform") or ""),
        "sent_at": f"{datetime.utcnow().isoformat()}Z",
    }

    if registry is None:
        save_sent_games(active_registry, path)


def prune_old_entries(registry: dict[str, Any], days: int = 90) -> int:
    """Remove entries older than `days` days from the registry and return the count."""
    sent_entries = _registry_sent_map(registry)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    keys_to_delete: list[str] = []

    for key, entry in sent_entries.items():
        if not isinstance(entry, dict):
            keys_to_delete.append(key)
            continue

        sent_at = _parse_sent_at(entry.get("sent_at"))
        if sent_at is None:
            keys_to_delete.append(key)
            continue

        if sent_at < cutoff:
            keys_to_delete.append(key)

    for key in keys_to_delete:
        sent_entries.pop(key, None)

    return len(keys_to_delete)
