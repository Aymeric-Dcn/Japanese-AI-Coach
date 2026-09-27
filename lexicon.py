"""
Word lookups in data/lexicon.db (filled by anki_sync.py and jlpt_data.py):
JLPT level, reading, meaning, whether you know the word.
"""

import json
import sqlite3
from functools import lru_cache
from pathlib import Path

LEXICON_PATH = Path("data") / "lexicon.db"
LEVELS = ["N5", "N4", "N3", "N2", "N1"]


def available() -> bool:
    return LEXICON_PATH.exists()


@lru_cache(maxsize=1)
def _index() -> dict:
    """{form: {"word", "reading", "meaning", "level", "known"}} — Anki entries win over the open lists,
    and a word listed at several levels keeps the easiest one."""
    index = {}
    if not LEXICON_PATH.exists():
        return index
    db = sqlite3.connect(LEXICON_PATH)
    rows = db.execute("SELECT word, reading, forms, meaning, level, known, source FROM words "
                      "ORDER BY CASE source WHEN 'anki' THEN 0 ELSE 1 END").fetchall()
    db.close()
    for word, reading, forms, meaning, level, known, source in rows:
        entry = {"word": word, "reading": reading, "meaning": meaning, "level": level, "known": bool(known)}
        for form in set(json.loads(forms or "[]")) | {word}:
            old = index.get(form)
            if old is None:
                index[form] = entry
            else:
                if not old["level"] and level:
                    old["level"] = level
                elif level and old["level"] and LEVELS.index(level) < LEVELS.index(old["level"]) and source != "anki":
                    old["level"] = level if not old["known"] else old["level"]
                if not old["meaning"] and meaning:
                    old["meaning"] = meaning
    return index


def lookup(form: str) -> dict:
    return _index().get(form)


def level(form: str) -> str:
    entry = lookup(form)
    return entry["level"] if entry else ""


def words(level_wanted: str = None) -> list:
    """Distinct entries, optionally of one JLPT level."""
    seen, result = set(), []
    for entry in _index().values():
        key = (entry["word"], entry["reading"])
        if key in seen or (level_wanted and entry["level"] != level_wanted):
            continue
        seen.add(key)
        result.append(entry)
    return result


def level_rank(lvl: str) -> int:
    """N5 → 0 … N1 → 4, unknown → 5."""
    return LEVELS.index(lvl) if lvl in LEVELS else 5
