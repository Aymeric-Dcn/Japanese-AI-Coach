#!/usr/bin/env python3
"""
Downloads open JLPT vocabulary lists (N5 → N1) into data/lexicon.db.

    python tools/jlpt_data.py

Source: open-anki-jlpt-decks by Jam Sinclair (MIT licence), built from Jonathan Waller's
JLPT lists on tanos.co.uk (CC BY). https://github.com/jamsinclair/open-anki-jlpt-decks

They give every word a JLPT level and an English meaning, so JLPT questions and levels work
even without the Full Japanese Study Deck (e.g. with another deck, or none). Words already
imported from your Anki keep their own data; the open lists fill the gaps.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))   # the project folder (coach/)

import csv
import io
import sqlite3
import sys
import urllib.request
from pathlib import Path

LEXICON_PATH = Path("data") / "lexicon.db"
CACHE = Path("data") / "jlpt"
URL = "https://raw.githubusercontent.com/jamsinclair/open-anki-jlpt-decks/main/src/n{level}.csv"


def download(level: int) -> str:
    path = CACHE / f"n{level}.csv"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL.format(level=level), timeout=60) as r:
            path.write_bytes(r.read())
    return path.read_text(encoding="utf-8")


def import_lists(log=print) -> int:
    rows = []
    for level in range(5, 0, -1):
        text = download(level)
        for row in csv.DictReader(io.StringIO(text)):
            word, reading = row.get("expression", "").strip(), row.get("reading", "").strip()
            if word:
                rows.append((word, reading, f'["{word}", "{reading}"]' if reading and reading != word else f'["{word}"]',
                             row.get("meaning", "").strip()[:160], f"N{level}"))
        log(f"  N{level}: {sum(1 for r in rows if r[4] == f'N{level}')} words")
    LEXICON_PATH.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(LEXICON_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS words (word TEXT, reading TEXT, forms TEXT, meaning TEXT, level TEXT,
                                          known INTEGER, source TEXT);
        CREATE INDEX IF NOT EXISTS idx_words_word ON words(word);
        CREATE INDEX IF NOT EXISTS idx_words_reading ON words(reading);""")
    db.execute("DELETE FROM words WHERE source = 'open'")
    db.executemany("INSERT INTO words VALUES (?, ?, ?, ?, ?, 0, 'open')", rows)
    db.commit()
    db.close()
    return len(rows)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    n = import_lists()
    print(f"✓ {n} words with their JLPT level added to {LEXICON_PATH}")


if __name__ == "__main__":
    main()
