"""Relevance scoring for Agave's puzzle and casual game portfolio.

Scoring philosophy:
- Mechanic-specific keyword groups give HIGH scores (these are exact matches)
- General puzzle/casual signals give MEDIUM scores
- Negative keywords (shooters, casino, etc.) give heavy penalties
- Score is capped at 100
- Scores below 30 are forced to 0 (noise) but the game's actual genre
  (Racing, Shooter, Casino, RPG, Sports, etc.) is still labeled so the
  HTML can filter by it.
"""

from __future__ import annotations

import re
from typing import Any

# =============================================================================
# Agave-relevant mechanics (positive scoring)
# =============================================================================

MECHANIC_GROUPS: dict[str, dict[str, Any]] = {
    "Hidden Object": {
        "keywords": [
            "hidden object", "find object", "find hidden", "seek and find",
            "search and find", "spot the difference", "find the difference",
            "i spy", "where's", "scene investigation", "detective scene",
        ],
        "weight": 35,
    },
    "Sort Puzzle": {
        "keywords": [
            "sort puzzle", "color sort", "water sort", "ball sort", "sort it",
            "sorting game", "sort the", "tube sort", "pour sort", "liquid sort",
        ],
        "weight": 35,
    },
    "Match-3": {
        "keywords": [
            "match 3", "match-3", "match three", "candy match", "jewel match",
            "gem match", "bubble match", "tile match", "swap match", "blast",
            "crush saga", "puzzle blast", "bubble shooter",
        ],
        "weight": 30,
    },
    "Jigsaw": {
        "keywords": [
            "jigsaw", "jig saw", "puzzle pieces", "picture puzzle",
            "fit pieces", "puzzle fit",
        ],
        "weight": 35,
    },
    "Merge": {
        "keywords": [
            "merge puzzle", "merge game", "merge mansion", "merge dragons",
            "merge magic", "combine merge", "evolve merge", "merge two",
        ],
        "weight": 30,
    },
    "Mahjong": {
        "keywords": [
            "mahjong", "tile connect", "onet", "tile match connect",
            "pair tiles", "matching tiles", "mahjongg",
        ],
        "weight": 35,
    },
    "Word": {
        "keywords": [
            "word game", "word puzzle", "word search", "wordsearch", "crossword",
            "word connect", "word link", "anagram", "word stack", "word swipe",
            "spell word", "letter puzzle", "scrabble", "word cookies",
        ],
        "weight": 35,
    },
    "Block / Hex": {
        "keywords": [
            "block puzzle", "hex puzzle", "wooden block", "tetris", "blockudoku",
            "block blast", "hexa", "hex blocks", "wood block",
        ],
        "weight": 30,
    },
    "Escape Room": {
        "keywords": [
            "escape room", "room escape", "escape puzzle", "mystery escape",
            "escape mystery", "puzzle escape",
        ],
        "weight": 30,
    },
    "Solitaire": {
        "keywords": [
            "solitaire", "klondike", "spider solitaire", "freecell",
            "tripeaks", "card solitaire", "patience card",
        ],
        "weight": 25,
    },
    "Sudoku / Logic": {
        "keywords": [
            "sudoku", "nonogram", "picross", "kakuro", "logic puzzle",
            "number puzzle", "minesweeper",
        ],
        "weight": 25,
    },
}

# General puzzle/casual signals — small boost when present
GENERAL_PUZZLE_KEYWORDS = [
    "puzzle", "casual", "brain teaser", "brain training", "relaxing puzzle",
    "puzzle game", "casual puzzle", "mind game", "logic game", "tap puzzle",
]
GENERAL_PUZZLE_WEIGHT = 8

# =============================================================================
# Non-relevant categories (we still label them so HTML can filter)
# =============================================================================

NON_RELEVANT_CATEGORIES: dict[str, list[str]] = {
    "Racing": [
        "racing", "race car", "drift", "car race", "motorcycle race",
        "kart racing", "bike race", "drag racing", "rally",
    ],
    "Shooter": [
        "shooter", "shooting", "fps", "first person shooter",
        "third person shooter", "gun game", "battle royale", "sniper",
    ],
    "Casino": [
        "casino", "slots", "slot machine", "poker", "blackjack", "roulette",
        "bingo", "lottery", "wheel of fortune",
    ],
    "RPG": [
        "rpg", "role playing", "role-playing", "mmorpg", "jrpg",
        "turn based rpg", "action rpg", "fantasy rpg",
    ],
    "Sports": [
        "soccer", "football", "basketball", "baseball", "tennis", "golf",
        "cricket", "boxing", "mma", "wrestling", "sports game",
    ],
    "Action / Arcade": [
        "action game", "arcade", "platformer", "runner", "endless runner",
        "fighting game", "beat em up",
    ],
    "Simulation": [
        "simulator", "tycoon", "farming sim", "life simulator", "city builder",
        "construction simulator", "truck simulator",
    ],
    "Strategy": [
        "strategy game", "rts", "tower defense", "real time strategy",
        "war strategy", "4x strategy",
    ],
    "Idle / Clicker": [
        "idle game", "clicker", "incremental game", "afk game",
        "idle tycoon", "tap tap",
    ],
    "Card / Board": [
        "card game", "deck builder", "ccg", "tcg", "trading card",
        "board game", "chess", "checkers",
    ],
}

# Hard penalties — these never belong in Agave's portfolio
NEGATIVE_KEYWORDS = [
    "casino", "slots", "slot machine", "poker", "blackjack", "roulette",
    "bingo", "lottery", "gambling", "betting", "sportsbook",
    "shooter", "fps", "battle royale", "sniper",
    "horror", "scary", "gore",
    "dating sim", "adult", "18+",
]
NEGATIVE_PENALTY = -40


def _normalize_text(*fields: Any) -> str:
    """Flatten game fields into a single lowercase searchable string."""
    parts: list[str] = []
    for field in fields:
        if not field:
            continue
        if isinstance(field, list):
            parts.extend(str(item) for item in field)
        else:
            parts.append(str(field))
    return " ".join(parts).lower()


def _count_keyword_hits(text: str, keywords: list[str]) -> int:
    hits = 0
    for kw in keywords:
        # Use word-boundary match for short keywords to avoid false positives
        if len(kw.split()) == 1 and len(kw) <= 4:
            if re.search(rf"\b{re.escape(kw)}\b", text):
                hits += 1
        else:
            if kw in text:
                hits += 1
    return hits


def _detect_non_relevant_category(text: str) -> str | None:
    """Return the best-matching non-relevant category, or None."""
    best_category = None
    best_hits = 0
    for category, keywords in NON_RELEVANT_CATEGORIES.items():
        hits = _count_keyword_hits(text, keywords)
        if hits > best_hits:
            best_hits = hits
            best_category = category
    return best_category if best_hits > 0 else None


def score_game(game: dict[str, Any]) -> tuple[int, str, str]:
    """Score a single game for Agave relevance.

    Returns (score, mechanic_label, reason).
    - score: int in [0, 100]. Anything below 30 is forced to 0 (noise).
    - mechanic_label: best matching mechanic, or non-relevant category, or "Other".
    - reason: short human-readable explanation.
    """
    text = _normalize_text(
        game.get("name"),
        game.get("description"),
        game.get("category"),
        game.get("subcategories"),
        game.get("keywords"),
    )

    # 1) Match against Agave-relevant mechanics
    best_mechanic: str | None = None
    best_mechanic_score = 0
    matched_keywords: list[str] = []

    for mechanic, cfg in MECHANIC_GROUPS.items():
        hits = _count_keyword_hits(text, cfg["keywords"])
        if hits > 0:
            mech_score = cfg["weight"] + (hits - 1) * 10
            if mech_score > best_mechanic_score:
                best_mechanic_score = mech_score
                best_mechanic = mechanic
                # Capture which keywords hit for the reason field
                matched_keywords = [
                    kw for kw in cfg["keywords"] if kw in text
                ][:3]

    # 2) General puzzle/casual signal
    general_hits = _count_keyword_hits(text, GENERAL_PUZZLE_KEYWORDS)
    general_score = min(general_hits * GENERAL_PUZZLE_WEIGHT, 25)

    # 3) Negative penalty
    negative_hits = _count_keyword_hits(text, NEGATIVE_KEYWORDS)
    negative_score = negative_hits * NEGATIVE_PENALTY

    # 4) Combine and cap
    raw_score = best_mechanic_score + general_score + negative_score
    final_score = max(0, min(100, raw_score))

    # 5) Decide label
    if best_mechanic and final_score >= 30:
        mechanic_label = best_mechanic
        reason_bits = []
        if matched_keywords:
            reason_bits.append(f"matched: {', '.join(matched_keywords)}")
        if general_hits:
            reason_bits.append(f"+{general_hits} general puzzle signal(s)")
        if negative_hits:
            reason_bits.append(f"-{negative_hits} negative signal(s)")
        reason = "; ".join(reason_bits) if reason_bits else "mechanic keywords matched"
    else:
        # Not relevant — try to label it with its actual genre so HTML can filter
        non_relevant = _detect_non_relevant_category(text)
        if non_relevant:
            mechanic_label = non_relevant
            reason = f"non-portfolio genre: {non_relevant.lower()}"
        elif general_hits:
            mechanic_label = "Other Casual"
            reason = "general casual signals only, no strong mechanic match"
        else:
            mechanic_label = "Other"
            reason = "no mechanic keywords matched"

    # 6) Force scores below 30 to zero — they're noise (we still keep the label)
    if final_score < 30:
        final_score = 0

    return final_score, mechanic_label, reason
