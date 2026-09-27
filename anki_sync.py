#!/usr/bin/env python3
"""
Reads the words and kanji you know from Anki and saves them to data/known.json.
Anki must be open, with the AnkiConnect add-on (code 2055492159).

    python anki_sync.py                     # cards with an interval ≥ 21 days ("mature")
    python anki_sync.py --min-interval 7    # also younger cards
    python anki_sync.py --min-interval 0    # every card already reviewed at least once

Made for the « Full Japanese Study Deck » note types (FJSD-Word, FJSD-Kanji); other note
types can be added with --word-type / --kanji-type (fields are read the same way).
make_exercises.py --known then only keeps sentences built from these words.
"""

import argparse
import datetime
import html
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ANKI_URL = "http://localhost:8765"
KNOWN_PATH = Path("data") / "known.json"

WORD_FIELDS = ["Kanji forms/Readings", "Readings/Kanji forms"]
KANJI_FIELDS = ["Kanji"]

JAPANESE = re.compile(r"[぀-ヿ㐀-鿿々〆ヶ]")
KANJI = re.compile(r"[㐀-鿿々]")


def anki(action: str, **params):
    body = json.dumps({"action": action, "version": 6, "params": params}).encode("utf-8")
    try:
        with urllib.request.urlopen(urllib.request.Request(ANKI_URL, data=body), timeout=120) as r:
            reply = json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError:
        sys.exit("Cannot reach AnkiConnect on localhost:8765. Is Anki open, with AnkiConnect installed?")
    if reply.get("error"):
        sys.exit(f"AnkiConnect error: {reply['error']}")
    return reply["result"]


# ---------------------------------------------------------------------------
# Reading the card fields (HTML)
# ---------------------------------------------------------------------------

def strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def forms_from_field(value: str) -> set:
    """All written forms and readings in a field such as
    <div class="entry"><span class="word word-kanjiform"><ruby><rb>彼処</rb><rt>あそこ</rt></ruby></span></div>
    → {"彼処", "あそこ"}."""
    value = re.sub(r"\[sound:[^\]]*\]", "", value)
    value = re.sub(r"<ul\b.*?</ul>", "", value, flags=re.S)           # notes attached to an entry
    chunks = re.split(r"</div>|<br\s*/?>|[、,;；\n]", value)
    forms = set()
    for chunk in chunks:
        if "<rt" in chunk:
            written = strip_tags(re.sub(r"<rt\b.*?</rt>", "", chunk, flags=re.S))
            reading = strip_tags(re.sub(r"<rb\b.*?</rb>", "", chunk, flags=re.S))
            candidates = [written, reading]
        else:
            candidates = [strip_tags(chunk)]
        for c in candidates:
            c = re.sub(r"\s+", "", c).strip("〜~・")
            if c and len(c) <= 15 and JAPANESE.search(c):
                forms.add(c)
    return forms


def notes_info(note_ids: list) -> list:
    notes = []
    for i in range(0, len(note_ids), 500):
        notes += anki("notesInfo", notes=note_ids[i:i + 500])
    return notes


def collect(note_type: str, fields: list, min_interval: int) -> tuple:
    """Returns (set of forms, number of notes) for the known notes of one note type."""
    query = f'"note:{note_type}" ' + (f"prop:ivl>={min_interval}" if min_interval > 0 else "-is:new")
    note_ids = anki("findNotes", query=query)
    forms = set()
    for note in notes_info(note_ids):
        for name in fields:
            if name in note["fields"]:
                forms |= forms_from_field(note["fields"][name]["value"])
    return forms, len(note_ids)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Saves the words and kanji you know in Anki to data/known.json.")
    p.add_argument("--min-interval", type=int, default=21,
                   help="minimum card interval in days (21 = mature, 0 = any reviewed card)")
    p.add_argument("--word-type", action="append", default=None,
                   help="note type holding words (repeatable, default: FJSD-Word)")
    p.add_argument("--kanji-type", action="append", default=None,
                   help="note type holding kanji (repeatable, default: FJSD-Kanji)")
    args = p.parse_args()

    words, kanji = set(), set()
    for note_type in args.word_type or ["FJSD-Word"]:
        forms, n = collect(note_type, WORD_FIELDS, args.min_interval)
        print(f"  {note_type}: {n} known notes → {len(forms)} forms")
        words |= forms
    for note_type in args.kanji_type or ["FJSD-Kanji"]:
        forms, n = collect(note_type, KANJI_FIELDS, args.min_interval)
        chars = {c for f in forms for c in f if KANJI.match(c)}
        print(f"  {note_type}: {n} known notes → {len(chars)} kanji")
        kanji |= chars

    KNOWN_PATH.parent.mkdir(exist_ok=True)
    KNOWN_PATH.write_text(json.dumps({
        "date": datetime.date.today().isoformat(),
        "min_interval": args.min_interval,
        "words": sorted(words),
        "kanji": sorted(kanji),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    sample = ", ".join(sorted(words)[:12])
    print(f"✓ {KNOWN_PATH}: {len(words)} words, {len(kanji)} kanji  (e.g. {sample}…)")


if __name__ == "__main__":
    main()
