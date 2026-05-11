"""Relevance scoring for Agave's puzzle and casual game portfolio.

Scoring philosophy:
- Mechanic-specific keyword groups give HIGH scores (these are exact matches)
- General puzzle/casual signals give MEDIUM scores
- Negative keywords (shooters, casino, etc.) give heavy penalties
- Score is capped 0-100
- Scores below 30 are force-zeroed (noise like shooters/racing/casino)
"""

from __future__ import annotations
from typing import Any


# ─── MECHANIC GROUPS ────────────────────────────────────────────────────────

MECHANIC_GROUPS: dict[str, list[str]] = {
    "Hidden Object": [
        "hidden object", "hidden objects", "find the hidden", "spot the difference",
        "seek and find", "search and find", "find hidden", "object hunt",
        "hidden items", "hidden things", "find the", "spot the", "find all",
        "hidden scene", "hidden picture", "eye spy", "i spy", "seek find",
    ],
    "Sort Puzzle": [
        "sort puzzle", "sorting puzzle", "color sort", "colour sort", "water sort",
        "blob sort", "tile sort", "stack sort", "yarn sort", "hex sort", "pipe sort",
        "sand sort", "liquid sort", "ball sort", "fruit sort", "vegetable sort",
        "candy sort", "object sort", "sort the", "sort and", "sorting game",
        "sort balls", "sort water", "pour water", "fill the",
    ],
    "Match-3 / Blast": [
        "match-3", "match 3", "match three", "match and blast", "blast puzzle",
        "pop blast", "jewel blast", "jewel match", "gem blast", "gem match",
        "candy crush", "royal match", "tile match", "match tiles", "bubble blast",
        "bubble pop", "bubble shooter", "match gems", "match jewels", "match candy",
        "match fruit", "match stars", "match items", "match and collect",
    ],
    "Jigsaw": [
        "jigsaw", "jigsaw puzzle", "puzzle pieces", "sliding puzzle", "slide puzzle",
        "tile puzzle", "15 puzzle", "picture puzzle", "photo puzzle", "image puzzle",
        "assemble", "piece together",
    ],
    "Merge Puzzle": [
        "merge puzzle", "merge game", "merge items", "merge anything", "merge and",
        "merge to", "merge dragons", "merge adventure", "combine items",
        "combine and merge", "merge chain", "merge evolution", "merge master",
        "merge county", "merge manor",
    ],
    "Block / Hex Puzzle": [
        "block puzzle", "hexa puzzle", "hex puzzle", "hexagon puzzle", "block blast",
        "wood block", "wooden block", "block drop", "block fill", "tetris",
        "falling blocks", "fit blocks", "block fit", "1010", "block game",
        "shape puzzle", "shape fit",
    ],
    "Word Puzzle": [
        "word puzzle", "word search", "word find", "word game", "crossword",
        "word connect", "wordscapes", "word cross", "find words", "make words",
        "word chain", "word link", "spelling", "vocabulary", "anagram",
        "scramble words", "word scramble", "letter puzzle", "find the word",
        "guess the word", "wordle", "word daily", "daily word",
    ],
    "Mahjong / Tile Connect": [
        "mahjong", "mahjong solitaire", "tile connect", "tile matching", "onet",
        "link tiles", "pair match", "tile pair", "connect tiles", "shisen", "shanghai",
    ],
    "Escape Room / Point & Click": [
        "escape room", "escape game", "escape puzzle", "point and click",
        "point & click", "room escape", "locked room", "mystery room",
        "puzzle adventure", "adventure puzzle",
    ],
    "Casual Puzzle": [
        "brain puzzle", "brain teaser", "mind puzzle", "logic puzzle", "casual puzzle",
        "fun puzzle", "number puzzle", "math puzzle", "color puzzle", "colour puzzle",
        "physics puzzle", "tricky puzzle", "riddle", "sudoku", "nonogram", "picross",
        "fill puzzle", "draw puzzle", "line puzzle", "connect dots", "connect the dots",
        "pipe puzzle", "pipe connect", "flow puzzle", "flow free", "arrow puzzle",
        "path puzzle", "maze puzzle", "slide to", "tap to", "drag and",
    ],
}

SUPPORTING_KEYWORDS: list[str] = [
    "puzzle", "casual", "relax", "relaxing", "relaxation", "calm", "chill", "cozy",
    "satisfying", "addictive", "match", "sort", "merge", "connect", "find", "hidden",
    "search", "seek", "collect", "solve", "brain", "logic", "think", "tile", "grid",
    "color", "colour", "word", "letter", "number", "mystery", "detective",
    "investigate", "clue", "escape", "room",
]

NEGATIVE_KEYWORDS: list[str] = [
    "shooter", "shooting", "first person shooter", "fps", "gun", "guns", "weapon",
    "weapons", "warfare", "war game", "battle royale", "combat", "fight",
    "fighting game", "beat em up", "beat 'em up", "hack and slash", "gore",
    "violent", "kill", "killing",
    "casino", "slot machine", "slot game", "poker", "blackjack", "roulette",
    "betting", "gambling", "jackpot", "spin to win", "lucky spin",
    "racing game", "car game", "driving game", "drift", "race track", "formula",
    "motocross", "truck game",
    "soccer game", "football game", "basketball game", "baseball game",
    "tennis game", "golf game", "sports game",
    "role playing", "rpg game", "dungeon crawler", "dungeon quest", "hack slash",
    "mmorpg", "action rpg", "turn based rpg",
    "idle tycoon", "idle game", "clicker game", "tap tap", "incremental game",
    "city builder", "base builder", "tower defense", "td game",
    "dating sim", "dating simulation", "romance game", "otome", "love story game",
    "real time strategy", "rts game", "strategy war", "clan war", "pvp battle",
]

CATEGORY_BONUSES: dict[str, int] = {
    "puzzle": 20, "casual": 15, "word": 15, "board": 10, "trivia": 5,
    "family": 5, "educational": 5, "brain": 10, "logic": 10,
}

NAME_BONUS_KEYWORDS: list[str] = [
    "puzzle", "sort", "match", "blast", "merge", "jigsaw", "hidden", "find",
    "word", "escape", "mahjong", "block", "hexa", "tile", "connect", "search",
    "seek", "brain", "logic", "sudoku", "crossword",
]


def _build_search_text(game: dict[str, Any]) -> str:
    keywords = game.get("keywords", [])
    if isinstance(keywords, list):
        keywords_str = " ".join(str(k) for k in keywords)
    else:
        keywords_str = str(keywords or "")

    subcategories = game.get("subcategories", [])
    if isinstance(subcategories, list):
        subcategories_str = " ".join(str(s) for s in subcategories)
    else:
        subcategories_str = str(subcategories or "")

    parts = [
        str(game.get("name") or ""),
        str(game.get("description") or ""),
        keywords_str,
        str(game.get("category") or ""),
        subcategories_str,
    ]
    return " ".join(parts).lower()


def _find_mechanic(text: str) -> tuple[str, int]:
    best_mechanic = "Unknown"
    best_hit_count = 0
    total_mechanic_score = 0

    for mechanic, keywords in MECHANIC_GROUPS.items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits > 0:
            total_mechanic_score += 40
            if hits > best_hit_count:
                best_hit_count = hits
                best_mechanic = mechanic

    capped_score = min(total_mechanic_score, 80)
    return best_mechanic, capped_score


def _supporting_score(text: str) -> int:
    hits = sum(1 for kw in SUPPORTING_KEYWORDS if kw in text)
    return min(hits * 8, 24)


def _negative_score(text: str) -> int:
    hits = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text)
    return hits * -35


def _category_bonus(game: dict[str, Any]) -> tuple[int, list[str]]:
    category = str(game.get("category") or "").lower()
    total = 0
    matched: list[str] = []
    for keyword, bonus in CATEGORY_BONUSES.items():
        if keyword in category:
            total += bonus
            matched.append(f"{keyword.title()} (+{bonus})")
    return total, matched


def _name_bonus(game: dict[str, Any]) -> int:
    name = str(game.get("name") or "").lower()
    for kw in NAME_BONUS_KEYWORDS:
        if kw in name:
            return 15
    return 0


def _build_reason(
    mechanic: str,
    mechanic_score: int,
    supporting: int,
    negative: int,
    category_parts: list[str],
    name_bonus: int,
    final_score: int,
) -> str:
    parts: list[str] = []

    if final_score == 0:
        return "Not relevant (noise — racing, shooter, casino, etc.)"

    if mechanic != "Unknown" and mechanic_score > 0:
        parts.append(f"Mechanic: {mechanic} (+{mechanic_score})")
    if supporting > 0:
        parts.append(f"General puzzle signals (+{supporting})")
    if category_parts:
        parts.append(f"Category: {', '.join(category_parts)}")
    if name_bonus > 0:
        parts.append(f"Strong puzzle name (+{name_bonus})")
    if negative < 0:
        parts.append(f"Negative signals ({negative})")
    if not parts:
        return "No relevant signals found."

    return " | ".join(parts) + f" → Score: {final_score}"


def score_game(game: dict[str, Any]) -> tuple[int, str, str]:
    """Score a game's relevance to Agave's puzzle/casual portfolio.

    Returns: (score 0-100, mechanic string, reason string)

    Note: scores below 30 are force-zeroed — these are noise (shooters,
    racing, casino games, etc.) that shouldn't show up as borderline.
    """
    text = _build_search_text(game)

    mechanic, mechanic_score = _find_mechanic(text)
    supporting = _supporting_score(text)
    negative = _negative_score(text)
    cat_bonus, cat_parts = _category_bonus(game)
    name_b = _name_bonus(game)

    raw_score = mechanic_score + supporting + negative + cat_bonus + name_b
    final_score = max(0, min(raw_score, 100))

    # ─── FORCE ZERO BELOW 30 ────────────────────────────────────────────────
    # Anything below 30 is noise — racing, shooters, casino, RPG, etc.
    # We don't want borderline scores like 10, 15, 25 cluttering the radar.
    if final_score < 30:
        final_score = 0
        mechanic = "Not Relevant"

    # Heavy negative penalty also marks as not relevant
    if final_score < 20 and negative < -35:
        mechanic = "Not Relevant"

    reason = _build_reason(
        mechanic=mechanic,
        mechanic_score=mechanic_score,
        supporting=supporting,
        negative=negative,
        category_parts=cat_parts,
        name_bonus=name_b,
        final_score=final_score,
    )

    # IMPORTANT: return order is (score, mechanic, reason)
    # main.py expects this order
    return final_score, mechanic, reason
