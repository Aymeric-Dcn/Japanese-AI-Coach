"""
Word lookups in data/lexicon.db (filled by anki_sync.py and jlpt_data.py):
JLPT level, reading, meaning, whether you know the word.
"""

import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

LEXICON_PATH = Path("data") / "lexicon.db"
LEVELS = ["N5", "N4", "N3", "N2", "N1"]
# Anki (FJSD) meanings glue the part-of-speech tags to the glosses: « traffic; transportationCommon noun; … »
TAG_START = re.compile(r"(?<=[a-z0-9)\]'.])(?=[A-Z])")
KANA_TAG = "Usually written using kana alone"


def short_meaning(meaning: str, glosses: int = 3) -> str:
    """First sense only, without the tags: « traffic; transportationCommon noun; … » → « traffic; transportation »."""
    if not meaning:
        return ""
    first = TAG_START.split(meaning, 1)[0]
    parts = [p.strip() for p in re.split(r"[;|]", first) if p.strip()]
    return "; ".join(parts[:glosses])


def first_sense_tags(meaning: str) -> list:
    """The tags right after the first sense (« Common noun », « Usually written using kana alone »…)."""
    pieces = TAG_START.split(meaning or "", 1)
    if len(pieces) < 2:
        return []
    tags = []
    for item in pieces[1].split(";"):
        item = item.strip()
        if not item or not item[0].isupper():
            break
        tags.append(item)
    return tags


def available() -> bool:
    return LEXICON_PATH.exists()


def _mtime() -> float:
    return LEXICON_PATH.stat().st_mtime if LEXICON_PATH.exists() else 0


def _index() -> dict:
    return _build_index(_mtime())  # rebuilt when anki_sync.py / jlpt_data.py update the file


@lru_cache(maxsize=1)
def _build_index(mtime: float) -> dict:
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
        kana = source == "anki" and KANA_TAG in first_sense_tags(meaning)
        entry = {"word": word, "reading": reading, "meaning": short_meaning(meaning), "level": level,
                 "known": bool(known), "kana": kana}
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
                    old["meaning"] = short_meaning(meaning)
                if kana and form == word and old["reading"] == reading:
                    old["kana"] = True
    return index


def lookup(form: str) -> dict:
    return _index().get(form)


def level(form: str) -> str:
    entry = lookup(form)
    return entry["level"] if entry else ""


def usually_kana(form: str) -> bool:
    """True for words normally written in kana (事 → こと, 為 → ため): no kanji question on them."""
    entry = lookup(form)
    return bool(entry and entry.get("kana"))


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
