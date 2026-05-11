"""Relevance scoring for Agave's puzzle and casual game portfolio.

Scoring philosophy:
- Game NAME match → strongest signal (weight x2)
- subtitle / short_description match → strong signal (weight x1.5)
- Description match → normal signal (weight x1)
- Short/ambiguous keywords only checked in name+subtitle, not full description
- Negative keywords (multi-word phrases only) subtract points
- Score capped 0-100
"""

from __future__ import annotations
from typing import Any


MECHANIC_GROUPS: dict[str, dict] = {
    "Hidden Object": {
        "keywords": [
            "hidden object", "hidden objects", "find the hidden",
            "spot the difference", "seek and find", "search and find",
            "find hidden", "object hunt", "hidden items", "hidden things",
            "hidden scene", "hidden picture", "i spy", "seek find",
            "find objects", "hidden mystery", "find and seek",
        ],
        "name_only_keywords": [
            "find all", "find the", "spot the", "eye spy",
        ],
        "weight": 40,
    },
    "Sort Puzzle": {
        "keywords": [
            "sort puzzle", "sorting puzzle", "color sort", "colour sort",
            "water sort", "blob sort", "tile sort", "stack sort", "yarn sort",
            "hex sort", "pipe sort", "sand sort", "liquid sort", "ball sort",
            "fruit sort", "candy sort", "object sort", "sorting game",
            "sort balls", "sort water", "pour water", "fill the tube",
            "color sorting", "colour sorting",
        ],
        "name_only_keywords": [
            "sort the", "sort and",
        ],
        "weight": 40,
    },
    "Match-3": {
        "keywords": [
            "match-3", "match 3", "match three", "match and blast",
            "blast puzzle", "jewel blast", "jewel match", "gem blast",
            "gem match", "candy crush", "royal match", "tile match",
            "match tiles", "bubble blast", "bubble pop", "bubble shooter",
            "match gems", "match jewels", "match candy", "match fruit",
            "match stars", "match and collect", "swap and match",
            "3 in a row", "three in a row",
        ],
        "name_only_keywords": [
            "match items", "pop blast",
        ],
        "weight": 38,
    },
    "Jigsaw": {
        "keywords": [
            "jigsaw", "jig saw", "jigsaw puzzle", "puzzle pieces",
            "picture puzzle", "photo puzzle", "image puzzle", "mosaic puzzle",
            "assemble puzzle", "piece together", "jigsaw pieces",
            "jigsaws", "jigsaw art",
        ],
        "name_only_keywords": [],
        "weight": 40,
    },
    "Merge": {
        "keywords": [
            "merge puzzle", "merge game", "merge items", "merge objects",
            "merge and collect", "merge to evolve", "merge dragons",
            "merge mansion", "merge magic", "merge adventure",
            "merge two", "merge same", "merge identical", "double merge",
            "merge chain", "combine and merge", "merge to unlock",
        ],
        "name_only_keywords": [],
        "weight": 38,
    },
    "Mahjong": {
        "keywords": [
            "mahjong", "mahjongg", "mah jong", "mah-jong",
            "tile connect", "onet connect", "tile pairing",
            "connect tiles", "tile elimination", "shisen-sho",
            "mahjong solitaire", "mahjong puzzle", "mahjong tiles",
            "mahjong game", "mahjong classic", "tile matching puzzle",
            "triple tile", "tile master",
        ],
        "name_only_keywords": [
            "pair matching",
        ],
        "weight": 42,
    },
    "Word": {
        "keywords": [
            "word puzzle", "word game", "word search", "wordsearch",
            "word find", "crossword", "word cross", "anagram",
            "scrambled words", "word scramble", "boggle", "letter puzzle",
            "spelling game", "vocabulary game", "word connect", "word link",
            "word chain", "word stack", "word cookies", "wordle",
            "find words", "find the word", "word builder", "word maker",
        ],
        "name_only_keywords": [
            "typeshift",
        ],
        "weight": 40,
    },
    "Block / Hex": {
        "keywords": [
            "block puzzle", "hex puzzle", "hexagon puzzle", "wood block",
            "wooden block", "block fit", "block drop", "block fill",
            "tetromino", "block game", "tangram", "hexa puzzle",
            "hex block", "block and fill", "wood puzzle", "brick puzzle",
            "fill the board", "block drop puzzle",
        ],
        "name_only_keywords": [
            "tetris",
        ],
        "weight": 38,
    },
    "Escape Room": {
        "keywords": [
            "escape room", "room escape", "escape puzzle", "escape game",
            "mystery room", "escape the room", "point and click",
            "escape adventure", "locked room", "escape mystery",
            "detective puzzle", "mystery puzzle",
        ],
        "name_only_keywords": [
            "adventure puzzle",
        ],
        "weight": 38,
    },
    "Solitaire": {
        "keywords": [
            "solitaire", "klondike", "freecell", "spider solitaire",
            "tripeaks", "tri peaks", "pyramid solitaire", "golf solitaire",
            "card solitaire", "patience game", "solitaire card",
        ],
        "name_only_keywords": [],
        "weight": 35,
    },
    "Sudoku / Logic": {
        "keywords": [
            "sudoku", "nonogram", "picross", "hitori", "kakuro",
            "number puzzle", "logic puzzle", "brain puzzle", "iq puzzle",
            "number game", "math puzzle", "logic game",
        ],
        "name_only_keywords": [],
        "weight": 35,
    },
}

# General signals — checked in full text, each +8, max +20
GENERAL_PUZZLE_KEYWORDS = [
    "puzzle game", "puzzle adventure", "puzzle challenge",
    "casual puzzle", "addictive puzzle", "fun puzzle",
    "brain teaser", "brain training", "relaxing puzzle",
    "tap to solve", "drag and drop puzzle", "casual game",
    "family puzzle", "relaxing game",
]
GENERAL_PUZZLE_WEIGHT = 8
GENERAL_PUZZLE_CAP = 20

# Negative — exact multi-word phrases only
NEGATIVE_KEYWORDS = [
    "first person shooter", "battle royale", "war game", "gun game",
    "car racing", "kart racing", "drift race", "racing game",
    "slot machine", "casino game", "gambling game", "betting game",
    "horror game", "gore game",
    "real time strategy", "tower defense",
    "dating sim", "visual novel",
]
NEGATIVE_WEIGHT = -35


def _texts(game: dict[str, Any]) -> tuple[str, str, str]:
    """Return (name_text, short_text, full_text) all lowercased.

    short_text = name + subtitle + short_description (most signal-dense)
    full_text  = everything including long description
    """
    name = str(game.get("name") or "").lower()
    subtitle = str(game.get("subtitle") or "").lower()
    short_desc = str(game.get("short_description") or "").lower()
    desc = str(game.get("description") or "").lower()
    cat = str(game.get("category") or "").lower()
    subs = " ".join(str(s) for s in (game.get("subcategories") or []))
    kws = " ".join(str(k) for k in (game.get("keywords") or []))

    short_text = " ".join(filter(None, [name, subtitle, short_desc]))
    full_text = " ".join(filter(None, [name, subtitle, short_desc, desc, cat, subs, kws]))
    return name, short_text, full_text


def score_game(game: dict[str, Any]) -> tuple[int, str, str]:
    """Score a game for Agave portfolio relevance.

    Returns (score 0-100, mechanic_label, reason).
    """
    name_text, short_text, full_text = _texts(game)

    best_mechanic: str | None = None
    best_score = 0
    best_kw: str | None = None
    best_source = "description"

    for mechanic, cfg in MECHANIC_GROUPS.items():
        w = cfg["weight"]

        # name_only keywords — double weight, only in name
        for kw in cfg.get("name_only_keywords", []):
            if kw in name_text:
                effective = w * 2
                if effective > best_score:
                    best_score = effective
                    best_mechanic = mechanic
                    best_kw = kw
                    best_source = "name"
                break

        # Regular keywords — check name first (x2), then subtitle/short_desc (x1.5), then full (x1)
        for kw in cfg["keywords"]:
            if kw in name_text:
                effective = w * 2
                source = "name"
            elif kw in short_text:
                effective = int(w * 1.5)
                source = "subtitle/short_desc"
            elif kw in full_text:
                effective = w
                source = "description"
            else:
                continue

            if effective > best_score:
                best_score = effective
                best_mechanic = mechanic
                best_kw = kw
                best_source = source
            break  # one match per group is enough

    # Cap mechanic contribution
    mechanic_contribution = min(best_score, 80)

    # General puzzle bonus
    general_bonus = 0
    general_hits: list[str] = []
    for kw in GENERAL_PUZZLE_KEYWORDS:
        if kw in full_text:
            general_bonus = min(general_bonus + GENERAL_PUZZLE_WEIGHT, GENERAL_PUZZLE_CAP)
            general_hits.append(kw)

    # Negative penalty
    negative_score = 0
    negative_hits: list[str] = []
    for kw in NEGATIVE_KEYWORDS:
        if kw in full_text:
            negative_score += NEGATIVE_WEIGHT
            negative_hits.append(kw)

    raw = mechanic_contribution + general_bonus + negative_score
    score = max(0, min(100, raw))

    if best_mechanic:
        mechanic_label = best_mechanic
        reason_parts = [f"{best_kw!r} in {best_source}"]
        if general_hits:
            reason_parts.append(f"bonus: {general_hits[0]}")
        if negative_hits:
            reason_parts.append(f"penalty: {', '.join(negative_hits)}")
        reason = "; ".join(reason_parts)
    else:
        mechanic_label = "Other"
        if general_hits:
            reason = f"general signals only: {', '.join(general_hits[:2])}"
        elif negative_hits:
            reason = f"penalized: {', '.join(negative_hits)}"
        else:
            reason = "no relevant keywords found"

    return score, mechanic_label, reason
