"""Relevance scoring for Agave's puzzle and casual game portfolio.

Scoring philosophy:
- Mechanic-specific keyword groups give HIGH scores (these are exact matches)
- General puzzle/casual signals give MEDIUM scores
- Negative keywords (shooters, casino, etc.) give heavy penalties
- Score is capped 0-100
"""

from __future__ import annotations
from typing import Any


# ─── MECHANIC GROUPS ─────────────────────────────────────────────────────────
# Each group: if ANY keyword matches → base weight points
# All keywords use exact substring match on lowercased combined text

MECHANIC_GROUPS: dict[str, dict] = {
    "Hidden Object": {
        "keywords": [
            "hidden object", "hidden objects", "find the hidden", "spot the difference",
            "seek and find", "search and find", "find hidden", "object hunt",
            "hidden items", "hidden things", "find the", "spot the", "find all",
            "hidden scene", "hidden picture", "eye spy", "i spy", "seek find",
        ],
        "weight": 40,
    },
    "Sort Puzzle": {
        "keywords": [
            "sort puzzle", "sorting puzzle", "color sort", "colour sort", "water sort",
            "blob sort", "tile sort", "stack sort", "yarn sort", "hex sort",
            "pipe sort", "sand sort", "liquid sort", "ball sort", "fruit sort",
            "candy sort", "object sort", "sort the", "sort and", "sorting game",
            "sort balls", "sort water", "pour water",
        ],
        "weight": 40,
    },
    "Match-3": {
        "keywords": [
            "match-3", "match 3", "match three", "match and blast", "blast puzzle",
            "pop blast", "jewel blast", "jewel match", "gem blast", "gem match",
            "candy crush", "royal match", "tile match", "match tiles",
            "bubble blast", "bubble pop", "bubble shooter",
            "match gems", "match jewels", "match candy", "match fruit",
            "match stars", "match items", "match and collect",
        ],
        "weight": 38,
    },
    "Jigsaw": {
        "keywords": [
            "jigsaw", "jig saw", "jigsaw puzzle", "puzzle pieces", "picture puzzle",
            "photo puzzle", "image puzzle", "mosaic puzzle", "assemble puzzle",
            "piece together", "jigsaw pieces",
        ],
        "weight": 40,
    },
    "Merge": {
        "keywords": [
            "merge puzzle", "merge game", "merge items", "merge objects",
            "merge and collect", "merge to evolve", "merge dragons", "merge mansion",
            "merge magic", "merge adventure", "merge two", "merge same",
            "merge identical", "double merge", "merge chain",
        ],
        "weight": 38,
    },
    "Mahjong": {
        "keywords": [
            "mahjong", "mahjongg", "mah jong", "mah-jong",
            "tile connect", "onet connect", "pair matching", "tile pairing",
            "connect tiles", "tile elimination", "shisen-sho",
        ],
        "weight": 40,
    },
    "Word": {
        "keywords": [
            "word puzzle", "word game", "word search", "wordsearch", "word find",
            "crossword", "word cross", "anagram", "scrambled words", "word scramble",
            "boggle", "letter puzzle", "spelling game", "vocabulary game",
            "word connect", "word link", "word chain", "word stack",
            "word cookies", "typeshift", "wordle",
        ],
        "weight": 40,
    },
    "Block / Hex": {
        "keywords": [
            "block puzzle", "hex puzzle", "hexagon puzzle", "wood block",
            "wooden block", "block fit", "block drop", "block fill",
            "tetris", "tetromino", "block game", "tangram",
            "hexa puzzle", "hex block", "block and fill",
        ],
        "weight": 38,
    },
    "Escape Room": {
        "keywords": [
            "escape room", "room escape", "escape puzzle", "escape game",
            "mystery room", "escape the room", "point and click",
            "adventure puzzle", "escape adventure",
        ],
        "weight": 38,
    },
    "Solitaire": {
        "keywords": [
            "solitaire", "klondike", "freecell", "spider solitaire",
            "tripeaks", "tri peaks", "pyramid solitaire", "golf solitaire",
            "card solitaire", "patience",
        ],
        "weight": 35,
    },
    "Sudoku / Logic": {
        "keywords": [
            "sudoku", "nonogram", "picross", "hitori", "kakuro",
            "number puzzle", "logic puzzle", "brain puzzle", "iq puzzle",
            "number game", "math puzzle",
        ],
        "weight": 35,
    },
}

# General puzzle/casual signals — each adds +8, capped at +20
GENERAL_PUZZLE_KEYWORDS = [
    "puzzle", "casual", "relaxing", "brain teaser", "brain training",
    "family friendly", "easy to play", "simple gameplay", "tap to",
    "swipe to", "drag and drop", "addictive puzzle", "fun puzzle",
    "puzzle adventure", "puzzle challenge", "puzzle game",
]
GENERAL_PUZZLE_WEIGHT = 8
GENERAL_PUZZLE_CAP = 20

# Negative keywords — each subtracts 30 points
NEGATIVE_KEYWORDS = [
    "shooter", "first person shooter", "fps", "battle royale",
    "war game", "military", "sniper", "gun game",
    "racing game", "car racing", "drift race", "kart race",
    "casino", "slot machine", "poker", "blackjack", "gambling", "betting",
    "horror", "scary", "gore", "violent",
    "mmorpg", "moba", "real time strategy", "tower defense",
    "dating sim", "visual novel",
]
NEGATIVE_WEIGHT = -30


def _build_text(game: dict[str, Any]) -> str:
    parts = [
        str(game.get("name") or ""),
        str(game.get("description") or ""),
        str(game.get("category") or ""),
        " ".join(game.get("subcategories") or []),
        " ".join(game.get("keywords") or []),
    ]
    return " ".join(parts).lower()


def score_game(game: dict[str, Any]) -> tuple[int, str, str]:
    """Score a game for Agave portfolio relevance.

    Returns (score 0-100, mechanic_label, reason).
    Scores below 60 are considered not relevant.
    """
    text = _build_text(game)

    # 1. Find best mechanic match
    best_mechanic: str | None = None
    best_mechanic_score = 0
    best_mechanic_keyword: str | None = None

    name_text = str(game.get("name") or "").lower()
    for mechanic, cfg in MECHANIC_GROUPS.items():
        for kw in cfg["keywords"]:
            if kw in text:
                # Prefer keyword that also matches the game name (more confident)
                name_bonus = 5 if kw in name_text else 0
                effective_score = cfg["weight"] + name_bonus
                if effective_score > best_mechanic_score:
                    best_mechanic_score = cfg["weight"]
                    best_mechanic = mechanic
                    best_mechanic_keyword = kw
                break  # one match per group is enough

    # 2. General puzzle bonus
    general_bonus = 0
    general_hits = []
    for kw in GENERAL_PUZZLE_KEYWORDS:
        if kw in text:
            general_bonus += GENERAL_PUZZLE_WEIGHT
            general_hits.append(kw)
            if general_bonus >= GENERAL_PUZZLE_CAP:
                general_bonus = GENERAL_PUZZLE_CAP
                break

    # 3. Negative penalty
    negative_score = 0
    negative_hits = []
    for kw in NEGATIVE_KEYWORDS:
        if kw in text:
            negative_score += NEGATIVE_WEIGHT
            negative_hits.append(kw)

    # 4. Total score
    raw = best_mechanic_score + general_bonus + negative_score
    score = max(0, min(100, raw))

    # 5. Build reason and label
    if best_mechanic:
        mechanic_label = best_mechanic
        reason_parts = [f"mechanic: {best_mechanic_keyword}"]
        if general_hits:
            reason_parts.append(f"puzzle signals: {', '.join(general_hits[:2])}")
        if negative_hits:
            reason_parts.append(f"penalties: {', '.join(negative_hits)}")
        reason = "; ".join(reason_parts)
    else:
        mechanic_label = "Other"
        if general_hits:
            reason = f"general puzzle signals only: {', '.join(general_hits[:3])}"
        elif negative_hits:
            reason = f"penalized: {', '.join(negative_hits)}"
        else:
            reason = "no relevant keywords found"

    return score, mechanic_label, reason
