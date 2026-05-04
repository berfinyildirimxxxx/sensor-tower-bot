"""Relevance scoring for Agave's puzzle and casual game portfolio."""

from __future__ import annotations

from typing import Any

HIGH_RELEVANCE_GROUPS: dict[str, list[str]] = {
    "Hidden Object": [
        "hidden object",
        "find the",
        "spot the",
        "seek and find",
        "search and find",
        "find them",
        "find it",
        "object hunt",
        "hidden items",
        "hidden things",
    ],
    "Sort Puzzle": [
        "sort puzzle",
        "color sort",
        "tile sort",
        "stack sort",
        "blob sort",
        "water sort",
        "yarn sort",
        "hex sort",
        "pipe sort",
    ],
    "Match-3": [
        "match-3",
        "match 3",
        "match three",
        "blast puzzle",
        "pop blast",
        "jewel blast",
        "candy crush",
        "royal match",
        "tile match",
    ],
    "Jigsaw": [
        "jigsaw",
        "jigsaw puzzle",
        "puzzle pieces",
        "sliding puzzle",
    ],
    "Merge Puzzle": [
        "merge puzzle",
        "merge game",
        "merge items",
        "merge anything",
    ],
    "Block/Hex Puzzle": [
        "block puzzle",
        "hexa puzzle",
        "hex puzzle",
        "hexagon puzzle",
        "block blast",
        "wood block",
    ],
    "Word Puzzle": [
        "word puzzle",
        "word search",
        "crossword",
        "word connect",
        "wordscapes",
    ],
}

MEDIUM_RELEVANCE_KEYWORDS: list[str] = [
    "puzzle",
    "brain teaser",
    "brain puzzle",
    "logic puzzle",
    "casual puzzle",
    "hidden",
    "mystery",
    "detective",
    "investigate",
    "clue",
    "find",
    "search",
    "spot",
    "locate",
    "discover",
    "seek",
    "sort",
    "arrange",
    "organize",
    "order",
    "stack",
    "match",
    "connect",
    "link",
    "chain",
    "tile",
    "grid",
    "board puzzle",
    "merge",
    "combine",
    "collect",
    "gather",
    "word",
    "letters",
    "vocabulary",
    "spelling",
]

NEGATIVE_KEYWORDS: list[str] = [
    "shooter",
    "shooting",
    "gun",
    "weapon",
    "war",
    "battle",
    "combat",
    "fight",
    "violent",
    "casino",
    "slot",
    "poker",
    "blackjack",
    "betting",
    "gambling",
    "racing",
    "driving",
    "car",
    "vehicle",
    "speed",
    "soccer",
    "football",
    "basketball",
    "sports",
    "rpg",
    "role playing",
    "adventure quest",
    "dungeon",
    "idle tycoon",
    "clicker",
    "idle game",
    "city builder",
    "dating",
    "romance",
    "love story",
]

NAME_BONUS_KEYWORDS: list[str] = [
    "puzzle",
    "sort",
    "match",
    "blast",
    "merge",
    "jigsaw",
    "hidden",
    "find",
]


def _normalize_list(value: Any) -> list[str]:
    """Normalize a list-like field into a list of strings."""
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _combined_text(game: dict[str, Any]) -> str:
    """Build the lowercase searchable text blob for a game."""
    parts = [
        str(game.get("name") or ""),
        str(game.get("description") or ""),
        " ".join(_normalize_list(game.get("keywords"))),
        str(game.get("category") or ""),
        " ".join(_normalize_list(game.get("subcategories"))),
    ]
    return " ".join(parts).lower()


def _match_keywords(text: str, keywords: list[str]) -> list[str]:
    """Return all keywords found in the given text."""
    return [keyword for keyword in keywords if keyword in text]


def _detect_mechanic(high_matches: dict[str, list[str]], text: str) -> str:
    """Detect the most likely mechanic based on high-value keyword hits."""
    best_mechanic = "Unknown"
    best_score = 0

    for mechanic, matches in high_matches.items():
        match_count = min(len(matches), 2)
        if match_count > best_score:
            best_score = match_count
            best_mechanic = mechanic

    if best_mechanic != "Unknown":
        return best_mechanic

    if "puzzle" in text or "brain teaser" in text or "casual puzzle" in text:
        return "Casual Puzzle"
    return "Unknown"


def _build_reason(
    mechanic: str,
    high_matches: dict[str, list[str]],
    medium_matches: list[str],
    negative_matches: list[str],
    category_bonus_parts: list[str],
    name_bonus: bool,
) -> str:
    """Build a short human-readable scoring reason."""
    reason_parts: list[str] = []

    mechanic_matches = high_matches.get(mechanic, [])
    if mechanic_matches:
        shown_matches = ", ".join(f"'{match}'" for match in mechanic_matches[:2])
        reason_parts.append(f"Matches {mechanic.lower()} keywords: {shown_matches}")
    elif medium_matches:
        shown_matches = ", ".join(f"'{match}'" for match in medium_matches[:3])
        reason_parts.append(f"General puzzle signals: {shown_matches}")

    if category_bonus_parts:
        reason_parts.append(f"Category: {'; '.join(category_bonus_parts)}")

    if name_bonus:
        reason_parts.append("Name contains strong puzzle terms (+15)")

    if negative_matches:
        shown_negative = ", ".join(f"'{match}'" for match in negative_matches[:2])
        reason_parts.append(f"Negative signals: {shown_negative}")

    if not reason_parts:
        return "No strong puzzle or casual relevance signals found"

    return ". ".join(reason_parts)


def score_game(game: dict[str, Any]) -> tuple[int, str, str]:
    """Score a game's relevance to Agave's portfolio.

    Returns: (score 0-100, reason string, mechanic string)
    score >= 70 → relevant, send to Slack
    score < 70 → not relevant, skip
    """
    text = _combined_text(game)
    name_text = str(game.get("name") or "").lower()
    category_text = str(game.get("category") or "").lower()

    score = 0
    high_matches: dict[str, list[str]] = {}

    for mechanic, keywords in HIGH_RELEVANCE_GROUPS.items():
        matches = _match_keywords(text, keywords)
        if matches:
            high_matches[mechanic] = matches
            score += min(len(matches), 2) * 25

    medium_matches = _match_keywords(text, MEDIUM_RELEVANCE_KEYWORDS)
    if medium_matches:
        score += len(medium_matches) * 15

    negative_matches = _match_keywords(text, NEGATIVE_KEYWORDS)
    if negative_matches:
        romance_terms = {"dating", "romance", "love story"}
        if not any(term in negative_matches for term in romance_terms) or "puzzle" not in text:
            score -= len(negative_matches) * 30

    category_bonus_parts: list[str] = []
    if "puzzle" in category_text:
        score += 20
        category_bonus_parts.append("Puzzle (+20)")
    if "casual" in category_text:
        score += 10
        category_bonus_parts.append("Casual (+10)")
    if "word" in category_text:
        score += 15
        category_bonus_parts.append("Word (+15)")

    name_bonus = any(keyword in name_text for keyword in NAME_BONUS_KEYWORDS)
    if name_bonus:
        score += 15

    score = max(0, min(score, 100))
    mechanic = _detect_mechanic(high_matches, text)
    if mechanic == "Unknown" and medium_matches:
        mechanic = "Casual Puzzle"

    reason = _build_reason(
        mechanic=mechanic,
        high_matches=high_matches,
        medium_matches=medium_matches,
        negative_matches=negative_matches,
        category_bonus_parts=category_bonus_parts,
        name_bonus=name_bonus,
    )

    return (score, reason, mechanic)
