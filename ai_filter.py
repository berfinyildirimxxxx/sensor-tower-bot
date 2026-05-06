"""AI-powered game relevance filter using Claude API.

Replaces the old rule-based relevance.py for scoring.
Sends batches of games to Claude and gets back structured relevance judgements.
Optionally analyses screenshot images for visual content signals.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Agave's core puzzle/casual portfolio mechanics
AGAVE_PORTFOLIO_CONTEXT = """
Agave is a mobile game publisher focused on puzzle and casual games.
Their portfolio includes:
- Hidden Object games (find hidden items in detailed scenes)
- Sort Puzzle games (color sort, blob sort, water sort, tile sort, etc.)
- Match-3 / Blast games (jewel blast, candy crush-style, royal match-style)
- Jigsaw Puzzle games
- Merge Puzzle games (merge items to progress)
- Block/Hex Puzzle games (block blast, hexa puzzle, wood block)
- Word Puzzle games (word search, crossword, word connect, wordscapes)

They are NOT interested in:
- Shooters, action games, combat games
- Casino, slot, poker, gambling games
- Racing, driving, car games
- Sports games (soccer, basketball, football)
- RPGs, dungeon crawlers, adventure quests
- Idle/clicker/tycoon games
- City builders
- Dating/romance simulations
"""

BATCH_PROMPT_TEMPLATE = """
You are a mobile game analyst for Agave, a puzzle and casual game publisher.
Evaluate each game below and decide if it is relevant to Agave's portfolio.

{portfolio_context}

For each game, respond with a JSON array. Each element must have:
- "app_id": the app_id from input
- "relevant": true or false
- "score": integer 0-100 (how relevant to Agave's puzzle/casual portfolio)
- "mechanic": the primary mechanic (e.g. "Hidden Object", "Sort Puzzle", "Match-3", "Word Puzzle", "Jigsaw", "Merge", "Block Puzzle", "Casual Puzzle", "Not Relevant")
- "reason": one sentence explaining why

Respond ONLY with a JSON array. No markdown, no backticks, no preamble.

Games to evaluate:
{games_json}
"""


def _fetch_screenshot_as_base64(url: str) -> str | None:
    """Download a screenshot and return base64-encoded JPEG data."""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "image/jpeg")
        if "image" not in content_type:
            return None
        return base64.b64encode(resp.content).decode("utf-8")
    except Exception as exc:
        logger.debug("Failed to fetch screenshot %s: %s", url, exc)
        return None


def _build_game_summary(game: dict[str, Any]) -> dict[str, str]:
    """Build a compact summary dict for one game to send to Claude."""
    keywords = game.get("keywords", [])
    if isinstance(keywords, list):
        keywords_str = ", ".join(str(k) for k in keywords[:20])
    else:
        keywords_str = str(keywords)

    subcategories = game.get("subcategories", [])
    if isinstance(subcategories, list):
        subcategories_str = ", ".join(str(s) for s in subcategories)
    else:
        subcategories_str = str(subcategories)

    description = str(game.get("description") or "")
    if len(description) > 400:
        description = description[:400] + "..."

    return {
        "app_id": str(game.get("app_id") or game.get("fid") or ""),
        "name": str(game.get("name") or ""),
        "category": str(game.get("category") or ""),
        "subcategories": subcategories_str,
        "keywords": keywords_str,
        "description": description,
    }


def _call_claude_api(
    messages: list[dict[str, Any]],
    system: str = "",
    max_tokens: int = 2000,
) -> str | None:
    """Call the Anthropic Claude API and return the text response."""
    import json as _json

    payload: dict[str, Any] = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        payload["system"] = system

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content", [])
        text = " ".join(
            block.get("text", "") for block in content if block.get("type") == "text"
        ).strip()
        return text or None
    except Exception as exc:
        logger.error("Claude API call failed: %s", exc)
        return None


def _parse_claude_response(text: str) -> list[dict[str, Any]]:
    """Parse Claude's JSON array response, stripping any markdown fences."""
    import json as _json

    cleaned = text.strip()
    # Strip markdown code fences if Claude added them despite instructions
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()

    try:
        result = _json.loads(cleaned)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            # Sometimes Claude wraps in {"results": [...]}
            for key in ("results", "games", "data"):
                if key in result and isinstance(result[key], list):
                    return result[key]
    except Exception as exc:
        logger.warning("Failed to parse Claude response as JSON: %s\nRaw: %s", exc, text[:500])

    return []


def score_games_with_claude(
    games: list[dict[str, Any]],
    batch_size: int = 8,
    use_screenshots: bool = True,
    screenshot_limit: int = 1,
) -> list[dict[str, Any]]:
    """Score a list of games using Claude API.

    Returns a list of dicts with keys: app_id, relevant, score, mechanic, reason.
    Games not returned by Claude (API errors, etc.) get score=0, relevant=False.
    """
    import json as _json

    if not games:
        return []

    all_results: list[dict[str, Any]] = []
    batches = [games[i : i + batch_size] for i in range(0, len(games), batch_size)]

    logger.info(
        "Scoring %d games with Claude API in %d batches (batch_size=%d).",
        len(games),
        len(batches),
        batch_size,
    )

    for batch_idx, batch in enumerate(batches):
        logger.info("Processing batch %d/%d (%d games)...", batch_idx + 1, len(batches), len(batch))

        summaries = [_build_game_summary(g) for g in batch]
        games_json = _json.dumps(summaries, ensure_ascii=False, indent=2)

        prompt = BATCH_PROMPT_TEMPLATE.format(
            portfolio_context=AGAVE_PORTFOLIO_CONTEXT,
            games_json=games_json,
        )

        # Build message content — optionally include screenshots for visual analysis
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

        if use_screenshots:
            for game in batch:
                screenshots = game.get("screenshots", [])
                if not isinstance(screenshots, list):
                    continue
                added = 0
                for screenshot_url in screenshots[:screenshot_limit]:
                    if added >= screenshot_limit:
                        break
                    b64 = _fetch_screenshot_as_base64(screenshot_url)
                    if b64:
                        app_id = str(game.get("app_id") or game.get("fid") or "")
                        name = str(game.get("name") or "")
                        content.append({
                            "type": "text",
                            "text": f"Screenshot for app_id={app_id} ({name}):",
                        })
                        content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            },
                        })
                        added += 1

        messages = [{"role": "user", "content": content}]
        response_text = _call_claude_api(messages, max_tokens=2000)

        if response_text is None:
            logger.warning("No response from Claude for batch %d; marking all as unscored.", batch_idx + 1)
            for game in batch:
                all_results.append({
                    "app_id": str(game.get("app_id") or game.get("fid") or ""),
                    "relevant": False,
                    "score": 0,
                    "mechanic": "Unknown",
                    "reason": "Claude API error — could not score.",
                })
            continue

        parsed = _parse_claude_response(response_text)
        scored_ids = {str(r.get("app_id", "")) for r in parsed}

        # Fill in any games Claude didn't return
        for game in batch:
            app_id = str(game.get("app_id") or game.get("fid") or "")
            if app_id not in scored_ids:
                parsed.append({
                    "app_id": app_id,
                    "relevant": False,
                    "score": 0,
                    "mechanic": "Unknown",
                    "reason": "Not returned by Claude.",
                })

        all_results.extend(parsed)

        # Be polite to the API between batches
        if batch_idx < len(batches) - 1:
            time.sleep(0.5)

    logger.info(
        "Claude scoring complete. %d/%d games marked relevant.",
        sum(1 for r in all_results if r.get("relevant")),
        len(all_results),
    )

    return all_results


def filter_relevant_games(
    games: list[dict[str, Any]],
    min_score: int = 60,
    batch_size: int = 8,
    use_screenshots: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Score all games and split into relevant/irrelevant.

    Returns: (relevant_items, all_scored_items)
    Each item is: {"game": ..., "score": ..., "mechanic": ..., "reason": ...}
    """
    scores = score_games_with_claude(
        games,
        batch_size=batch_size,
        use_screenshots=use_screenshots,
    )

    score_by_app_id: dict[str, dict[str, Any]] = {
        str(r.get("app_id", "")): r for r in scores
    }

    relevant: list[dict[str, Any]] = []
    all_scored: list[dict[str, Any]] = []

    for game in games:
        app_id = str(game.get("app_id") or game.get("fid") or "")
        score_data = score_by_app_id.get(app_id, {})

        item = {
            "game": game,
            "score": int(score_data.get("score", 0)),
            "mechanic": str(score_data.get("mechanic", "Unknown")),
            "reason": str(score_data.get("reason", "")),
            "relevant": bool(score_data.get("relevant", False)),
        }
        all_scored.append(item)

        if item["score"] >= min_score and item["relevant"]:
            relevant.append(item)

    logger.info(
        "Relevance filter: %d relevant out of %d total (min_score=%d).",
        len(relevant),
        len(all_scored),
        min_score,
    )

    return relevant, all_scored
