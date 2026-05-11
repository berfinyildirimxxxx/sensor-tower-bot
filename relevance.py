"""Relevance scoring for Agave's puzzle and casual game portfolio.

Scoring philosophy:
- Game NAME match → strongest signal (weight x2)
- subtitle match → strong signal (weight x2, same as name — very reliable)
- short_description match → normal signal (weight x1)
- Description match → normal signal (weight x1)
- Negative keywords use word-boundary matching to avoid false positives
  ("no slot machine" should NOT penalize a jigsaw game)
- Score capped 0-100
"""

from __future__ import annotations
import re
from typing import Any


MECHANIC_GROUPS: dict[str, dict] = {
    "Hidden Object": {
        "keywords": [
            "hidden object", "hidden objects", "find the hidden",
            "spot the difference", "seek and find", "search and find",
            "find hidden", "object hunt", "hidden items", "hidden things",
            "hidden scene", "hidden picture", "i spy", "seek find",
            "find objects", "hidden mystery", "find and seek",
            "hidden item", "object search",
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
            "color sorting", "colour sorting", "sort colors", "sort colour",
            "sort the balls", "sort the colors", "sort the colours",
            "tube puzzle", "tube sort",
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
            "3 in a row", "three in a row", "match-blast", "match blast",
            "pop puzzle", "pop and blast",
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
            "jigsaws", "jigsaw art", "jigsaw collection",
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
            "merge master", "merge defense",
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
            "triple tile", "tile master", "triple match",
            "pair tiles", "link tiles", "tile link",
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
            "word hunt", "letters puzzle", "word quest",
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
            "fill the board", "block drop puzzle", "block blast",
            "hex match", "hexagon match",
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
            "detective puzzle", "mystery puzzle", "escape house",
            "can you escape", "escape challenge",
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
            "solitaire puzzle", "card patience",
        ],
        "name_only_keywords": [],
        "weight": 35,
    },
    "Sudoku / Logic": {
        "keywords": [
            "sudoku", "nonogram", "picross", "hitori", "kakuro",
            "number puzzle", "logic puzzle", "brain puzzle", "iq puzzle",
            "number game", "math puzzle", "logic game", "number fill",
            "fill in numbers",
        ],
        "name_only_keywords": [],
        "weight": 35,
    },
}

# General signals
GENERAL_PUZZLE_KEYWORDS = [
    "puzzle game", "puzzle adventure", "puzzle challenge",
    "casual puzzle", "addictive puzzle", "fun puzzle",
    "brain teaser", "brain training", "relaxing puzzle",
    "tap to solve", "drag and drop puzzle", "casual game",
    "family puzzle", "relaxing game", "mind game",
]
GENERAL_PUZZLE_WEIGHT = 8
GENERAL_PUZZLE_CAP = 20

# Negative — ONLY used in name+subtitle (not full description)
# This prevents "no slot machine" in a jigsaw game description from penalizing it
NAME_NEGATIVE_KEYWORDS = [
    "casino", "slots", "slot machine", "poker", "blackjack",
    "gambling", "betting", "bingo cash",
    "shooter", "fps", "battle royale",
    "car racing", "kart racing", "drift race",
    "horror", "gore",
]
NAME_NEGATIVE_WEIGHT = -40

# In full description, only penalize if the phrase is unambiguous
DESC_NEGATIVE_KEYWORDS = [
    "first person shooter", "battle royale game",
    "car racing game", "kart racing game",
    "casino game", "gambling game", "betting game",
    "horror game",
    "real time strategy", "tower defense game",
    "dating sim", "visual novel game",
]
DESC_NEGATIVE_WEIGHT = -25


def _texts(game: dict[str, Any]) -> tuple[str, str, str]:
    """Return (name_text, title_text, full_text) all lowercased.

    title_text = name + subtitle (most reliable, treat like name)
    full_text  = everything
    """
    name = str(game.get("name") or "").lower()
    subtitle = str(game.get("subtitle") or "").lower()
    short_desc = str(game.get("short_description") or "").lower()
    desc = str(game.get("description") or "").lower()
    cat = str(game.get("category") or "").lower()
    subs = " ".join(str(s) for s in (game.get("subcategories") or []))
    kws = " ".join(str(k) for k in (game.get("keywords") or []))

    title_text = " ".join(filter(None, [name, subtitle]))
    full_text = " ".join(filter(None, [name, subtitle, short_desc, desc, cat, subs, kws]))
    return name, title_text, full_text


def _kw_in(text: str, kw: str) -> bool:
    """Check keyword in text. For single words use word boundary."""
    if len(kw.split()) == 1:
        return bool(re.search(rf'\b{re.escape(kw)}\b', text))
    return kw in text


def score_game(game: dict[str, Any]) -> tuple[int, str, str]:
    """Score a game for Agave portfolio relevance.

    Returns (score 0-100, mechanic_label, reason).
    """
    name_text, title_text, full_text = _texts(game)

    best_mechanic: str | None = None
    best_score = 0
    best_kw: str | None = None
    best_source = "description"

    for mechanic, cfg in MECHANIC_GROUPS.items():
        w = cfg["weight"]

        # name_only keywords — only in name (not even subtitle)
        for kw in cfg.get("name_only_keywords", []):
            if _kw_in(name_text, kw):
                effective = w * 2
                if effective > best_score:
                    best_score = effective
                    best_mechanic = mechanic
                    best_kw = kw
                    best_source = "name"
                break

        # Regular keywords
        # name or subtitle → x2 (title is very reliable)
        # full text → x1
        for kw in cfg["keywords"]:
            if kw in title_text:
                effective = w * 2
                source = "name/subtitle"
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
            break

    mechanic_contribution = min(best_score, 80)

    # General puzzle bonus (full text)
    general_bonus = 0
    general_hits: list[str] = []
    for kw in GENERAL_PUZZLE_KEYWORDS:
        if kw in full_text:
            general_bonus = min(general_bonus + GENERAL_PUZZLE_WEIGHT, GENERAL_PUZZLE_CAP)
            general_hits.append(kw)

    # Negative penalties
    # 1) In name/subtitle — strong single-word check
    name_penalty = 0
    name_penalty_hits: list[str] = []
    for kw in NAME_NEGATIVE_KEYWORDS:
        if _kw_in(title_text, kw):
            name_penalty += NAME_NEGATIVE_WEIGHT
            name_penalty_hits.append(kw)

    # 2) In description — only unambiguous multi-word phrases
    desc_penalty = 0
    desc_penalty_hits: list[str] = []
    # Only apply description penalty if no strong mechanic match
    if mechanic_contribution < 40:
        for kw in DESC_NEGATIVE_KEYWORDS:
            if kw in full_text:
                desc_penalty += DESC_NEGATIVE_WEIGHT
                desc_penalty_hits.append(kw)

    total_penalty = name_penalty + desc_penalty
    raw = mechanic_contribution + general_bonus + total_penalty
    score = max(0, min(100, raw))

    if best_mechanic:
        mechanic_label = best_mechanic
        reason_parts = [f"{best_kw!r} in {best_source}"]
        if general_hits:
            reason_parts.append(f"bonus: {general_hits[0]}")
        if name_penalty_hits:
            reason_parts.append(f"name-penalty: {', '.join(name_penalty_hits)}")
        if desc_penalty_hits:
            reason_parts.append(f"desc-penalty: {', '.join(desc_penalty_hits)}")
        reason = "; ".join(reason_parts)
    else:
        mechanic_label = "Other"
        if general_hits:
            reason = f"general signals only: {', '.join(general_hits[:2])}"
        elif name_penalty_hits:
            reason = f"penalized (name): {', '.join(name_penalty_hits)}"
        else:
            reason = "no relevant keywords found"

    return score, mechanic_label, reason
