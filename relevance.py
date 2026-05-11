"""Mechanic classification for mobile games (Agave Game Radar).

Public API:
    score_game(game: dict) -> dict

Returns:
    score              int   0–100 overall portfolio relevance
    mechanic           str   primary mechanic label
    mechanic_confidence int  0–100 confidence in the mechanic pick
    mechanic_signals   list  [{keyword, field, tier, pts}, ...] — debug evidence
    secondary_mechanics list [mechanic_str, ...]
    mechanic_family    str   broad group (Match / Logic / Casual / etc.)
    reason             str   human-readable explanation

Scoring design:
    - Every text field is inspected; field source sets a weight multiplier.
    - Each mechanic has "strong" phrases (base 30 pts) and "weak" tokens (base 10 pts).
    - Per field we take at most one strong OR one weak match (no description stuffing).
    - Negative contra-signals deduct points (strongest-field occurrence only).
    - A small category-prior bonus nudges likely mechanics without hard-coding them.
    - "Other Puzzle" is never scored directly — it is only a fallback label.
"""
from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Field weights (higher = more reliable signal)
# ---------------------------------------------------------------------------
FIELD_WEIGHTS: dict[str, float] = {
    "name":              3.0,
    "subtitle":          2.5,
    "intel_sub_genre":   1.8,
    "intel_genre":       1.5,
    "intel_theme":       1.3,
    "short_description": 1.5,
    "subcategories":     1.2,
    "keywords":          1.2,
    "description":       1.0,
    "intel_category":    0.8,
    "category":          0.8,
}

# Max raw points a single field can contribute per mechanic (before multiplier)
FIELD_CAP: dict[str, int] = {
    "name":              90,
    "subtitle":          90,
    "intel_sub_genre":   60,
    "intel_genre":       60,
    "intel_theme":       50,
    "short_description": 60,
    "subcategories":     50,
    "keywords":          50,
    "description":       60,
    "intel_category":    30,
    "category":          30,
}

STRONG = 30   # base points for a highly-specific phrase
WEAK   = 10   # base points for a single-word or generic signal


# ---------------------------------------------------------------------------
# Mechanic taxonomy
# ---------------------------------------------------------------------------
# strong  : explicit multi-word phrases — high-precision
# weak    : single words or generic terms — low-precision, tie-break only
# negative: contra-signals (subtract STRONG × field_weight; worst field wins)
# priors  : intel_category values that add a small bonus
# ---------------------------------------------------------------------------
MECHANICS: dict[str, dict] = {

    "Block": {
        "strong": [
            "block puzzle", "wood block", "wooden block", "block drop", "block fill",
            "tetromino", "hexa puzzle", "hex puzzle", "hexagon puzzle", "tangram",
            "block blast", "block fit", "wood puzzle", "brick puzzle", "hex block",
            "fill the grid", "block drop puzzle", "wooden puzzle", "block game puzzle",
            "pixel block", "pixel block puzzle", "block puzzle game",
        ],
        "weak": ["tetris", "hexagon", "blocks puzzle"],
        "negative": [],
        "priors": ["Puzzle", "Casual"],
    },

    "Bubble Shooter": {
        "strong": [
            "bubble shooter", "bubble shoot", "shoot bubbles", "pop bubbles",
            "bubble burst", "aim and shoot", "bubble cannon", "bubble match",
            "color bubble", "bubble shooting", "bubble breaker", "shoot the bubble",
            "bubble pop game", "pop the bubble",
        ],
        "weak": ["bubble shooter", "shoot pop"],
        "negative": ["soap bubble"],
        "priors": ["Casual", "Arcade"],
    },

    "Environmental": {
        "strong": [
            "environmental puzzle", "nature puzzle", "eco puzzle", "garden puzzle",
            "plant puzzle", "forest puzzle", "eco game", "nature game", "garden game",
            "ecology puzzle", "wildlife puzzle", "environment puzzle",
        ],
        "weak": ["eco game", "nature game", "garden game"],
        "negative": [],
        "priors": ["Casual", "Family"],
    },

    "Escape Room": {
        "strong": [
            "escape room", "room escape", "escape the room", "escape puzzle",
            "mystery room", "locked room", "can you escape", "escape challenge",
            "escape adventure", "escape mystery", "escape house", "escape game",
            "point and click", "detective puzzle", "mystery puzzle",
            "room mystery", "100 rooms", "100 doors", "mystery escape",
            "adventure escape", "escape island",
        ],
        "weak": ["escape room", "adventure puzzle"],
        # "escape the maze" belongs to Maze, not Escape Room
        "negative": ["escape the maze", "maze escape"],
        "priors": ["Puzzle", "Casual"],
    },

    "Hidden Objects": {
        "strong": [
            "hidden object", "hidden objects", "find the hidden", "spot the difference",
            "seek and find", "find hidden items", "hidden scene", "hidden picture",
            "object hunt", "i spy", "find the difference", "hidden mystery",
            "hidden item", "find and seek", "hidden things", "object search",
            "search and find", "find all hidden",
        ],
        "weak": ["find all", "spot the", "eye spy"],
        "negative": [],
        "priors": ["Casual", "Puzzle", "Family"],
    },

    "Jigsaw": {
        "strong": [
            "jigsaw", "jig saw", "jigsaw puzzle", "puzzle pieces", "picture puzzle",
            "photo puzzle", "assemble pieces", "piece together", "jigsaw pieces",
            "jigsaws", "jigsaw art", "jigsaw collection", "mosaic puzzle",
        ],
        "weak": ["puzzle piece", "assemble", "image puzzle"],
        "negative": [],
        "priors": ["Casual", "Family", "Puzzle"],
    },

    "Match Blast": {
        "strong": [
            "match and blast", "blast puzzle", "jewel blast", "gem blast",
            "candy blast", "match blast", "pop blast", "pop and blast",
            "blast match", "match and pop", "blast away match",
        ],
        "weak": ["blast match", "pop match"],
        # bubble blast belongs to Bubble Shooter, not Match Blast
        "negative": ["bubble blast", "bubble shooter"],
        "priors": ["Puzzle", "Casual"],
    },

    "Match Chain": {
        "strong": [
            "match chain", "chain match", "line match", "connect match",
            "chain puzzle", "connect and match", "chain reaction puzzle",
            "line connect match", "chain collapse", "link match",
            "draw match", "color chain match",
        ],
        "weak": ["chain match", "link and match"],
        "negative": [],
        "priors": ["Puzzle", "Casual"],
    },

    "Match Merge 2": {
        "strong": [
            "merge puzzle", "merge game", "merge items", "merge objects",
            "merge and collect", "merge to evolve", "merge dragons", "merge mansion",
            "merge magic", "merge two", "merge same", "merge identical",
            "double merge", "merge adventure", "merge and upgrade",
            "merge master", "merge defense", "merge to unlock",
            "combine and merge", "2048", "merge tile", "merge tiles",
            "number merge", "merge numbers", "merge number", "double tile",
            "merge kingdom", "merge empire", "merge story",
        ],
        "weak": ["merge game", "combine identical"],
        "negative": ["triple merge", "merge three", "merge 3", "triple match"],
        "priors": ["Puzzle", "Casual"],
    },

    "Match Merge 3": {
        "strong": [
            "triple match", "merge three", "triple merge", "merge 3",
            "three of a kind", "tile master", "triple tile",
            "match three tiles", "triple town", "collect three same",
            "three way merge",
        ],
        "weak": ["triple tiles", "three same tiles"],
        "negative": [],
        "priors": ["Puzzle", "Casual"],
    },

    "Match Pair": {
        "strong": [
            "mahjong", "mahjongg", "mah jong", "mah-jong", "tile connect",
            "onet connect", "tile pairing", "pair tiles", "link tiles",
            "tile link", "tile matching puzzle", "memory match", "flip and match",
            "find the pair", "match pairs", "matching pairs", "pair matching",
            "concentration game", "memory game", "tile elimination",
            "shisen-sho", "mahjong solitaire", "mahjong puzzle",
        ],
        "weak": ["mahjong", "tile pairs"],
        # "solitaire" alone belongs to the Solitaire mechanic
        "negative": ["klondike", "freecell", "spider solitaire", "tripeaks"],
        "priors": ["Puzzle", "Casual", "Board"],
    },

    "Solitaire": {
        "strong": [
            "solitaire", "klondike", "freecell", "spider solitaire",
            "tripeaks", "tri peaks", "tri-peaks", "pyramid solitaire",
            "golf solitaire", "card solitaire", "patience game", "solitaire card",
            "solitaire puzzle", "card patience", "solitaire classic",
            "solitaire collection", "solitaire adventure", "daily solitaire",
            "undo solitaire", "offline solitaire",
        ],
        "weak": ["solitaire", "patience"],
        # mahjong solitaire is actually a tile-matching game → Match Pair
        "negative": ["mahjong solitaire"],
        "priors": ["Card", "Casual", "Board"],
    },

    "Match Swap": {
        "strong": [
            "match-3", "match 3", "match three", "swap and match", "swap tiles",
            "swap gems", "jewel match", "candy crush", "three in a row",
            "3 in a row", "match tiles", "swap to match", "swap and blast",
            "match and swap", "gem swap",
        ],
        "weak": ["jewel match", "gem match"],
        "negative": [],
        "priors": ["Puzzle", "Casual"],
    },

    "Maze": {
        "strong": [
            "maze puzzle", "maze game", "find the exit", "labyrinth",
            "navigate the maze", "solve the maze", "maze runner",
            "maze challenge", "maze adventure", "escape the maze",
            "maze explorer", "maze solver", "maze path",
        ],
        "weak": ["maze", "labyrinth"],
        "negative": [],
        "priors": ["Puzzle", "Casual", "Family"],
    },

    "Numbers": {
        "strong": [
            # sudoku family
            "sudoku", "sudoku puzzle", "daily sudoku", "sudoku classic",
            "sudoku master", "sudoku challenge", "sudoku brain",
            # other logic number puzzles
            "nonogram", "picross", "kakuro", "hitori", "kenken",
            "fillomino", "slitherlink", "numberlink",
            # generic number puzzle
            "number puzzle", "math puzzle", "number game", "number fill",
            "number chain", "number connect", "fill in numbers", "number grid",
            "math game", "arithmetic puzzle", "number logic",
            "math challenge", "calculation puzzle", "number brain",
            # pixel / color-by-number (mechanic is identical: fill cells by number)
            "color by number", "colour by number", "paint by number",
            "pixel art color", "pixel color", "pixel coloring",
            "number coloring", "color pixel", "pixel art puzzle",
            "color by num", "pixel paint",
        ],
        "weak": ["sudoku", "numbers game", "math game", "pixel art"],
        "negative": [],
        "priors": ["Puzzle", "Board", "Educational"],
    },

    "Physics": {
        "strong": [
            "physics puzzle", "physics game", "physics based", "gravity puzzle",
            "balance puzzle", "slingshot puzzle", "catapult puzzle", "angry birds",
            "cut the rope", "projectile puzzle", "momentum puzzle", "ragdoll",
            "elastic puzzle", "physics engine", "weight puzzle",
        ],
        "weak": ["physics", "gravity", "slingshot"],
        "negative": [],
        "priors": ["Puzzle", "Casual", "Arcade"],
    },

    "Real-Time Puzzle": {
        "strong": [
            "real time puzzle", "real-time puzzle", "timed puzzle",
            "against the clock", "time pressure puzzle", "speed puzzle",
            "reflex puzzle", "arcade puzzle", "race against time",
            "time limited puzzle", "quick reflex", "speed match",
        ],
        "weak": ["timed puzzle", "reflex game"],
        "negative": [],
        "priors": ["Arcade", "Casual", "Puzzle"],
    },

    "Riddle": {
        "strong": [
            "riddle", "riddles", "brain teaser", "lateral thinking",
            "logic riddle", "trick question", "iq puzzle", "iq test",
            "mind teaser", "brain challenge", "common sense quiz",
            "brain teasers", "logic brain", "reasoning puzzle",
        ],
        "weak": ["riddle", "iq game", "brain teaser"],
        "negative": [],
        "priors": ["Puzzle", "Trivia", "Educational"],
    },

    "Screw": {
        "strong": [
            "screw puzzle", "unscrew", "pin puzzle", "bolt puzzle",
            "remove screw", "screw master", "nuts and bolts", "screw out",
            "screw jam", "iron bolt", "loosen screw", "pull the pin",
            "pull pin", "remove pins", "pin out", "bolt remove",
            "screw it out", "unscrew puzzle",
        ],
        "weak": ["screw", "bolt", "pin out"],
        "negative": [],
        "priors": ["Puzzle", "Casual"],
    },

    "Sort": {
        "strong": [
            "sort puzzle", "sorting puzzle", "color sort", "colour sort",
            "water sort", "blob sort", "tile sort", "stack sort", "yarn sort",
            "hex sort", "pipe sort", "sand sort", "liquid sort", "ball sort",
            "fruit sort", "candy sort", "sorting game", "sort balls",
            "sort water", "pour water", "fill the tube", "color sorting",
            "sort the balls", "sort the colors", "sort the colours",
            "tube puzzle", "tube sort",
        ],
        "weak": ["sorting game", "color sort"],
        "negative": [],
        "priors": ["Puzzle", "Casual"],
    },

    "Trivia": {
        "strong": [
            "trivia", "quiz game", "quiz show", "knowledge game",
            "general knowledge", "trivia game", "quiz challenge",
            "trivia challenge", "trivia night", "pub quiz", "trivia questions",
            "quiz night", "quiz app", "trivia quiz", "knowledge quiz",
        ],
        "weak": ["trivia", "quiz", "knowledge test"],
        "negative": [],
        "priors": ["Trivia", "Family", "Educational"],
    },

    "Word": {
        "strong": [
            "word puzzle", "word game", "word search", "wordsearch", "crossword",
            "word cross", "anagram", "word scramble", "boggle", "letter puzzle",
            "spelling game", "vocabulary game", "word connect", "word link",
            "word chain", "word stack", "word cookies", "wordle", "find words",
            "word builder", "word maker", "word hunt", "letters puzzle",
            "word quest", "word finder", "letter game",
        ],
        "weak": ["word game", "word puzzle", "spelling"],
        "negative": [],
        "priors": ["Word", "Family", "Educational"],
    },
}

# When no mechanic fires above threshold, fall back to this per intel_category
CATEGORY_FALLBACK: dict[str, str] = {
    "Puzzle":      "Other Puzzle",
    "Casual":      "Other Puzzle",
    "Word":        "Word",
    "Trivia":      "Trivia",
    "Board":       "Other Puzzle",
    "Family":      "Other Puzzle",
    "Arcade":      "Real-Time Puzzle",
    "Card":        "Solitaire",      # card store category → most likely solitaire
    "Educational": "Numbers",
}

# Mechanic family grouping (for UI color / grouping)
MECHANIC_FAMILIES: dict[str, str] = {
    "Match Swap":       "Match",
    "Match Blast":      "Match",
    "Match Chain":      "Match",
    "Match Merge 2":    "Match",
    "Match Merge 3":    "Match",
    "Match Pair":       "Match",
    "Sort":             "Casual Logic",
    "Screw":            "Casual Logic",
    "Block":            "Casual Logic",
    "Numbers":          "Logic",
    "Riddle":           "Logic",
    "Maze":             "Logic",
    "Physics":          "Physics",
    "Jigsaw":           "Casual",
    "Hidden Objects":   "Casual",
    "Environmental":    "Casual",
    "Escape Room":      "Casual",
    "Solitaire":        "Card",
    "Bubble Shooter":   "Arcade",
    "Real-Time Puzzle": "Arcade",
    "Word":             "Language",
    "Trivia":           "Knowledge",
    "Other Puzzle":     "Other",
}

CATEGORY_PRIOR_BONUS     = 8
MIN_CONFIDENCE_THRESHOLD = 20   # mechanic score must exceed this to be trusted

# General "puzzle-ness" signals — boost overall score but don't affect mechanic
GENERAL_PUZZLE_SIGNALS = [
    "puzzle game", "brain teaser", "brain training", "relaxing puzzle",
    "casual puzzle", "addictive puzzle", "fun puzzle", "tap to solve",
    "casual game", "family puzzle", "relaxing game", "mind game",
]
GENERAL_PUZZLE_BASE  = 6
GENERAL_PUZZLE_MAX   = 18

# Name-level negatives — penalize overall score
NAME_NEGATIVES = [
    "casino", "slot machine", "poker", "blackjack", "gambling",
    "betting", "fps", "first-person shooter", "battle royale",
    "car racing", "kart racing", "horror", "gore",
]
NAME_NEGATIVE_PENALTY = -35


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
_NORM_SEP  = re.compile(r'[\s\-–—_/|,;:]+')
_NORM_QUOT = re.compile(r"[''`]")


def _normalize(text: str) -> str:
    t = str(text or "").lower()
    t = _NORM_QUOT.sub("", t)
    t = _NORM_SEP.sub(" ", t)
    return t.strip()


def _keyword_in(text: str, kw: str) -> bool:
    """Left-anchored word-boundary match — plurals and suffixes included.

    Leading \\b prevents matching inside longer words (e.g. 'sort' won't fire
    on 'assorted').  No trailing \\b so 'block' also matches 'blocks',
    'bubble' matches 'bubbles', 'escape' matches 'escaped', etc.
    Multi-word phrases follow the same rule: 'hidden object' matches
    'hidden objects', 'merge tile' matches 'merge tiles'.
    """
    return bool(re.search(rf'\b{re.escape(kw)}', text))


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def _extract_fields(game: dict[str, Any]) -> list[tuple[str, str]]:
    """Return [(field_name, normalized_text), ...] for all non-empty fields."""
    out: list[tuple[str, str]] = []

    def _add(name: str, val: Any) -> None:
        if val:
            out.append((name, _normalize(str(val))))

    _add("name",              game.get("name"))
    _add("subtitle",          game.get("subtitle"))
    _add("short_description", game.get("short_description"))
    _add("description",       game.get("description"))
    _add("intel_genre",       game.get("intel_genre"))
    _add("intel_sub_genre",   game.get("intel_sub_genre"))
    _add("intel_theme",       game.get("intel_theme"))
    _add("intel_category",    game.get("intel_category"))
    _add("category",          game.get("category"))

    subs = game.get("subcategories") or []
    if subs:
        _add("subcategories", " ".join(str(s) for s in subs))

    kws = game.get("keywords") or []
    if kws:
        _add("keywords", " ".join(str(k) for k in kws))

    return out


# ---------------------------------------------------------------------------
# Per-mechanic scorer
# ---------------------------------------------------------------------------

def _score_mechanic(
    cfg: dict,
    fields: list[tuple[str, str]],
    intel_category_display: str,
) -> tuple[float, list[dict]]:
    """Score one mechanic against all fields. Returns (score, signals)."""
    signals: list[dict] = []
    total = 0.0

    for field_name, text in fields:
        mult = FIELD_WEIGHTS.get(field_name, 1.0)
        cap  = FIELD_CAP.get(field_name, 50)
        raw  = 0

        # One strong match per field (first hit wins — put most specific phrases first)
        for kw in cfg["strong"]:
            if _keyword_in(text, _normalize(kw)):
                raw = STRONG
                signals.append({"keyword": kw, "field": field_name, "tier": "strong", "pts": STRONG})
                break
        else:
            # No strong match — try weak
            for kw in cfg["weak"]:
                if _keyword_in(text, _normalize(kw)):
                    raw = WEAK
                    signals.append({"keyword": kw, "field": field_name, "tier": "weak", "pts": WEAK})
                    break

        total += min(raw, cap) * mult

    # Negatives: deduct based on the strongest-field match
    for neg_kw in cfg.get("negative", []):
        norm_neg = _normalize(neg_kw)
        best_w = 0.0
        best_field = ""
        for field_name, text in fields:
            if _keyword_in(text, norm_neg):
                w = FIELD_WEIGHTS.get(field_name, 1.0)
                if w > best_w:
                    best_w = w
                    best_field = field_name
        if best_field:
            penalty = int(STRONG * best_w)
            total -= penalty
            signals.append({"keyword": neg_kw, "field": best_field, "tier": "negative", "pts": -penalty})

    # Category prior nudge
    if intel_category_display in cfg.get("priors", []):
        total += CATEGORY_PRIOR_BONUS
        signals.append({
            "keyword": intel_category_display,
            "field": "category_prior",
            "tier": "prior",
            "pts": CATEGORY_PRIOR_BONUS,
        })

    return max(0.0, total), signals


# ---------------------------------------------------------------------------
# Classification pipeline
# ---------------------------------------------------------------------------

def _classify(game: dict[str, Any]) -> dict[str, Any]:
    fields = _extract_fields(game)
    cat_display = str(game.get("intel_category") or game.get("category") or "")

    # Score every real mechanic
    scores: dict[str, float] = {}
    all_signals: dict[str, list[dict]] = {}
    for mname, cfg in MECHANICS.items():
        sc, sigs = _score_mechanic(cfg, fields, cat_display)
        scores[mname] = sc
        all_signals[mname] = sigs

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_name, best_score = ranked[0]

    if best_score >= MIN_CONFIDENCE_THRESHOLD:
        mechanic   = best_name
        confidence = min(100, int(best_score))
        signals    = all_signals[best_name]
    else:
        mechanic   = CATEGORY_FALLBACK.get(cat_display, "Other Puzzle")
        confidence = 0
        signals    = []

    # Secondary: score >= threshold AND >= 50% of winner
    secondary = [
        n for n, s in ranked[1:5]
        if n != mechanic
        and s >= MIN_CONFIDENCE_THRESHOLD
        and s >= best_score * 0.5
    ]

    return {
        "mechanic":           mechanic,
        "mechanic_confidence": confidence,
        "mechanic_signals":   signals,
        "secondary_mechanics": secondary,
        "mechanic_family":    MECHANIC_FAMILIES.get(mechanic, "Other"),
    }


# ---------------------------------------------------------------------------
# Overall relevance score
# ---------------------------------------------------------------------------

def _relevance_score(game: dict[str, Any], mechanic_confidence: int) -> tuple[int, str]:
    """Compute 0–100 portfolio relevance. Returns (score, reason_prefix)."""
    fields   = _extract_fields(game)
    all_text = " ".join(t for _, t in fields)

    # General puzzle bonus
    bonus      = 0
    bonus_hits: list[str] = []
    for kw in GENERAL_PUZZLE_SIGNALS:
        if _normalize(kw) in all_text:
            bonus = min(bonus + GENERAL_PUZZLE_BASE, GENERAL_PUZZLE_MAX)
            bonus_hits.append(kw)

    # Name-level negative penalty
    name_text = _normalize(
        str(game.get("name") or "") + " " + str(game.get("subtitle") or "")
    )
    penalty      = 0
    penalty_hits: list[str] = []
    for kw in NAME_NEGATIVES:
        if _keyword_in(name_text, _normalize(kw)):
            penalty += NAME_NEGATIVE_PENALTY
            penalty_hits.append(kw)

    raw   = mechanic_confidence + bonus + penalty
    score = max(0, min(100, raw))

    parts: list[str] = []
    if mechanic_confidence > 0:
        parts.append(f"confidence: {mechanic_confidence}")
    if bonus_hits:
        parts.append(f"general: {bonus_hits[0]!r}")
    if penalty_hits:
        parts.append(f"penalized: {', '.join(penalty_hits)}")

    return score, "; ".join(parts) if parts else "no relevant signals"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_game(game: dict[str, Any]) -> dict[str, Any]:
    """Classify mechanic and compute portfolio relevance for one game.

    Returns a dict with:
        score               int   0–100
        mechanic            str
        mechanic_confidence int   0–100
        mechanic_signals    list  [{keyword, field, tier, pts}, ...]
        secondary_mechanics list  [str, ...]
        mechanic_family     str
        reason              str   human-readable, suitable for UI display
    """
    cls    = _classify(game)
    score, score_reason = _relevance_score(game, cls["mechanic_confidence"])

    # Prepend the top positive signal to reason for readability
    top = next(
        (s for s in cls["mechanic_signals"] if s["tier"] in ("strong", "weak")),
        None,
    )
    if top:
        reason = f"{top['keyword']!r} in {top['field']} [{top['tier']}]; {score_reason}"
    else:
        reason = score_reason

    return {
        "score":               score,
        "mechanic":            cls["mechanic"],
        "mechanic_confidence": cls["mechanic_confidence"],
        "mechanic_signals":    cls["mechanic_signals"],
        "secondary_mechanics": cls["secondary_mechanics"],
        "mechanic_family":     cls["mechanic_family"],
        "reason":              reason,
    }
