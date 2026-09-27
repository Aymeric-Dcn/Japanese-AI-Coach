#!/usr/bin/env python3
"""
Reads what you know in Anki — no need to open Anki.

    python anki_sync.py                     # mature cards (interval ≥ 21 days)
    python anki_sync.py --min-interval 0    # every card already reviewed
    python anki_sync.py --setup             # detect your note types and write data/anki.json (then edit it if needed)
    python anki_sync.py --source ankiconnect   # through the AnkiConnect add-on instead (Anki must be open)

By default the collection file itself is read (a copy of it, so it is never modified), which works
whether Anki is open or not. Any deck works: the word / kanji / grammar note types and their fields
are detected automatically the first time and saved in data/anki.json, which you can edit
(e.g. to use several decks, or a friend's deck).

Writes:
  data/known.json    words and kanji you know (used by make_exercises.py --known)
  data/lexicon.db    every word of your word notes: forms, reading, meaning, JLPT level, known or not
                     (+ the open JLPT lists if you ran jlpt_data.py)
  data/grammar.json  grammar notes (point, JLPT level, meaning, usage, example sentences)
  data/kanji.json    kanji notes (readings, meaning, level)
"""

import argparse
import datetime
import html
import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

DATA = Path("data")
KNOWN_PATH = DATA / "known.json"
CONFIG_PATH = DATA / "anki.json"
LEXICON_PATH = DATA / "lexicon.db"
GRAMMAR_PATH = DATA / "grammar.json"
KANJI_PATH = DATA / "kanji.json"
ANKI_URL = "http://localhost:8765"

JAPANESE = re.compile(r"[぀-ヿ㐀-鿿々〆ヶ]")
KANJI = re.compile(r"[㐀-鿿々]")
KANA_ONLY = re.compile(r"^[぀-ヿー・]+$")

# Known layouts (the Full Japanese Study Deck); anything else is detected automatically.
KNOWN_LAYOUTS = {
    "FJSD-Word": {"role": "word", "forms": ["Kanji forms/Readings", "Readings/Kanji forms"], "meaning": "Translations"},
    "FJSD-Kanji": {"role": "kanji", "forms": ["Kanji"], "meaning": "Meanings", "onyomi": "Onyomi", "kunyomi": "Kunyomi"},
    "FJSD-Grammar": {"role": "grammar", "point": "Point", "meaning": "Meaning", "usage": "Usage", "phrases": "Phrases"},
}
MEANING_NAMES = re.compile(r"meaning|translation|english|gloss|definition|sens|traduction|français|back|意味", re.I)
READING_NAMES = re.compile(r"reading|kana|yomi|furigana|lecture|読み", re.I)
WORD_NAMES = re.compile(r"word|expression|vocab|kanji|front|japanese|japonais|単語|語彙|表記", re.I)


# ---------------------------------------------------------------------------
# Reading field values (HTML)
# ---------------------------------------------------------------------------

def strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def clean_text(value: str, limit: int = 300) -> str:
    value = re.sub(r"\[sound:[^\]]*\]", "", value)
    value = re.sub(r"<br\s*/?>|</div>|</li>|</p>", "\n", value)
    text = strip_tags(value)
    text = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return text[:limit]


def forms_from_field(value: str) -> set:
    """All written forms and readings in a field such as
    <div class="entry"><span class="word word-kanjiform"><ruby><rb>彼処</rb><rt>あそこ</rt></ruby></span></div>
    → {"彼処", "あそこ"}. Also handles Anki's furigana syntax 彼処[あそこ]."""
    value = re.sub(r"\[sound:[^\]]*\]", "", value)
    value = re.sub(r"<ul\b.*?</ul>", "", value, flags=re.S)           # notes attached to an entry
    chunks = re.split(r"</div>|<br\s*/?>|</li>|\n", value)
    forms = set()
    for chunk in chunks:
        if "<rt" in chunk:
            written = strip_tags(re.sub(r"<rt\b.*?</rt>", "", chunk, flags=re.S))
            reading = strip_tags(re.sub(r"<rb\b.*?</rb>", "", chunk, flags=re.S))
            candidates = [written, reading]
        else:
            plain = strip_tags(chunk)
            if "[" in plain and "]" in plain:  # Anki furigana: 学校[がっこう] / 行[い]く
                written = re.sub(r"\[[^\]]*\]", "", plain)
                reading = re.sub(r"[^\s\[\]、,;；/／]+?\[([^\]]*)\]", r"\1", plain)
                candidates = [written, reading]
            else:
                candidates = [plain]
        for text in candidates:
            for c in re.split(r"[、,;；/／]", text):  # several forms in one entry
                c = re.split(r"\s[-–—:=]\s", c)[0]          # « 一緒に - together »
                c = re.sub(r"\s+", "", c).strip("〜~・()（）")
                if c and len(c) <= 15 and JAPANESE.search(c):
                    forms.add(c)
    return forms


def level_of(decks: list, tags: list) -> str:
    """JLPT level from the deck path (…::Vocab::N5) or the tags (JLPT_N5, grammar::n5)."""
    for deck in decks:
        for part in reversed(deck.split("::")):
            m = re.match(r"^\s*(?:JLPT[ _-]?)?N([1-5])\s*$", part, re.I)
            if m:
                return f"N{m.group(1)}"
    for tag in tags:
        m = re.search(r"(?:^|[:_])n([1-5])$", tag.lower())
        if m:
            return f"N{m.group(1)}"
    return ""


# ---------------------------------------------------------------------------
# Configuration: which note types hold words / kanji / grammar
# ---------------------------------------------------------------------------

def detect_layout(name: str, sample: list) -> dict:
    """Guesses the role and the useful fields of a note type from a sample of its notes."""
    if name in KNOWN_LAYOUTS:
        return dict(KNOWN_LAYOUTS[name])
    if not sample:
        return {"role": "ignore"}
    fields = list(sample[0]["fields"])
    if re.search(r"grammar|grammaire|文法", name, re.I):
        text_fields = [f for f in fields if any(JAPANESE.search(n["fields"].get(f, "")) for n in sample)]
        return {"role": "grammar", "point": text_fields[0] if text_fields else fields[0],
                "meaning": next((f for f in fields if MEANING_NAMES.search(f)), ""),
                "usage": next((f for f in fields if re.search(r"usage|structure|form", f, re.I)), ""),
                "phrases": next((f for f in fields if re.search(r"phrase|example|sentence|exemple|例", f, re.I)), "")}

    def share(field, test):
        values = [strip_tags(n["fields"].get(field, "")).strip() for n in sample]
        values = [v for v in values if v]
        return sum(1 for v in values if test(v)) / max(1, len(sample))

    single_kanji = {f: share(f, lambda v: len(v) == 1 and KANJI.match(v)) for f in fields}
    best_kanji = max(single_kanji, key=single_kanji.get)
    if single_kanji[best_kanji] >= 0.8:
        return {"role": "kanji", "forms": [best_kanji],
                "meaning": next((f for f in fields if MEANING_NAMES.search(f)), "")}

    def looks_like_word(v):
        forms = forms_from_field(v)
        return bool(forms) and all(len(x) <= 10 for x in forms)

    scores = {f: share(f, looks_like_word) + (0.15 if WORD_NAMES.search(f) else 0) for f in fields}
    ranked = sorted(fields, key=lambda f: -scores[f])
    if scores[ranked[0]] < 0.6:
        return {"role": "ignore"}  # sentence cards, cloze notes, other languages…
    forms = [ranked[0]]
    reading = next((f for f in fields if f != ranked[0] and READING_NAMES.search(f) and scores[f] >= 0.5), None)
    if reading:
        forms.append(reading)
    return {"role": "word", "forms": forms, "meaning": next((f for f in fields if MEANING_NAMES.search(f)), "")}


def setup_config(col, write: bool = True) -> dict:
    counts = col.note_types()
    layouts = {}
    for name, n in sorted(counts.items(), key=lambda x: -x[1]):
        sample = col.notes([name], limit=60)
        layouts[name] = detect_layout(name, sample)
        layouts[name]["notes"] = n
    config = {"source": "file", "profile": None, "collection_path": None, "min_interval": 21,
              "note_types": layouts}
    if write:
        DATA.mkdir(exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


# ---------------------------------------------------------------------------
# Sync from the collection file
# ---------------------------------------------------------------------------

def sync_from_file(config: dict, min_interval: int, log=print) -> dict:
    import anki_db
    col = anki_db.AnkiCollection.open(config.get("collection_path"), config.get("profile"))
    try:
        log(f"  collection: {col.path}")
        if not config.get("note_types"):
            log("  first run: detecting your note types (saved in data/anki.json)…")
            config.update(setup_config(col, write=False))
            DATA.mkdir(exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        layouts = config["note_types"]
        used = [n for n, l in layouts.items() if l.get("role") in ("word", "kanji", "grammar")]
        notes = col.notes(used)
    finally:
        col.close()

    def is_known(note):
        return note["max_interval"] >= min_interval if min_interval > 0 else note["reviewed"]

    words, kanji_info, grammar, known_words, known_kanji = [], {}, [], set(), set()
    for note in notes:
        layout = layouts[note["type"]]
        f = note["fields"]
        level = level_of(note["decks"], note["tags"])
        known = is_known(note)
        if layout["role"] == "word":
            forms = set()
            for name in layout.get("forms", []):
                forms |= forms_from_field(f.get(name, ""))
            if not forms:
                continue
            written = sorted((x for x in forms if KANJI.search(x)), key=len)
            readings = sorted((x for x in forms if KANA_ONLY.match(x)), key=len)
            meaning = clean_text(f.get(layout.get("meaning", ""), ""), 160).replace("\n", "; ")
            words.append({"word": (written or readings or sorted(forms))[0], "reading": readings[0] if readings else "",
                          "forms": sorted(forms), "meaning": meaning, "level": level, "known": known})
            if known:
                known_words |= forms
        elif layout["role"] == "kanji":
            chars = {c for name in layout.get("forms", []) for c in strip_tags(f.get(name, "")) if KANJI.match(c)}
            for c in chars:
                kanji_info[c] = {"meaning": clean_text(f.get(layout.get("meaning", ""), ""), 120).replace("\n", "; "),
                                 "onyomi": sorted(forms_from_field(f.get(layout.get("onyomi", ""), ""))),
                                 "kunyomi": sorted(forms_from_field(f.get(layout.get("kunyomi", ""), ""))),
                                 "level": level, "known": known}
                if known:
                    known_kanji.add(c)
        elif layout["role"] == "grammar":
            point = clean_text(f.get(layout.get("point", ""), ""), 80).replace("\n", " / ")
            if point:
                grammar.append({"point": point, "level": level,
                                "meaning": clean_text(f.get(layout.get("meaning", ""), ""), 300),
                                "usage": clean_text(f.get(layout.get("usage", ""), ""), 300),
                                "phrases": clean_text(f.get(layout.get("phrases", ""), ""), 1200),
                                "known": known})
    return {"words": words, "kanji": kanji_info, "grammar": grammar,
            "known_words": known_words, "known_kanji": known_kanji}


# ---------------------------------------------------------------------------
# Sync through AnkiConnect (fallback: known words and kanji only)
# ---------------------------------------------------------------------------

def anki_connect(action: str, **params):
    body = json.dumps({"action": action, "version": 6, "params": params}).encode("utf-8")
    with urllib.request.urlopen(urllib.request.Request(ANKI_URL, data=body), timeout=120) as r:
        reply = json.loads(r.read().decode("utf-8"))
    if reply.get("error"):
        raise RuntimeError(f"AnkiConnect error: {reply['error']}")
    return reply["result"]


def sync_from_ankiconnect(config: dict, min_interval: int, log=print) -> dict:
    layouts = config.get("note_types") or {k: dict(v) for k, v in KNOWN_LAYOUTS.items()}
    known_words, known_kanji = set(), set()
    for name, layout in layouts.items():
        if layout.get("role") not in ("word", "kanji"):
            continue
        query = f'"note:{name}" ' + (f"prop:ivl>={min_interval}" if min_interval > 0 else "-is:new")
        ids = anki_connect("findNotes", query=query)
        for i in range(0, len(ids), 500):
            for note in anki_connect("notesInfo", notes=ids[i:i + 500]):
                for field in layout.get("forms", []):
                    value = note["fields"].get(field, {}).get("value", "")
                    forms = forms_from_field(value)
                    if layout["role"] == "word":
                        known_words |= forms
                    else:
                        known_kanji |= {c for x in forms for c in x if KANJI.match(c)}
        log(f"  {name}: {len(ids)} known notes")
    return {"words": [], "kanji": {}, "grammar": [], "known_words": known_words, "known_kanji": known_kanji}


# ---------------------------------------------------------------------------
# Writing the results
# ---------------------------------------------------------------------------

def write_lexicon(words: list) -> int:
    """Rebuilds the Anki part of data/lexicon.db (open JLPT lists imported by jlpt_data.py are kept)."""
    DATA.mkdir(exist_ok=True)
    db = sqlite3.connect(LEXICON_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS words (word TEXT, reading TEXT, forms TEXT, meaning TEXT, level TEXT,
                                          known INTEGER, source TEXT);
        CREATE INDEX IF NOT EXISTS idx_words_word ON words(word);
        CREATE INDEX IF NOT EXISTS idx_words_reading ON words(reading);""")
    db.execute("DELETE FROM words WHERE source = 'anki'")
    db.executemany("INSERT INTO words VALUES (?, ?, ?, ?, ?, ?, 'anki')",
                   [(w["word"], w["reading"], json.dumps(w["forms"], ensure_ascii=False), w["meaning"],
                     w["level"], int(w["known"])) for w in words])
    db.commit()
    db.close()
    return len(words)


def sync(source: str = None, min_interval: int = None, log=print) -> dict:
    """Runs the sync and writes every output file. Returns a short summary."""
    config = load_config()
    source = source or config.get("source", "file")
    min_interval = config.get("min_interval", 21) if min_interval is None else min_interval
    if source == "file":
        try:
            result = sync_from_file(config, min_interval, log)
        except FileNotFoundError as e:
            log(f"  {e} — trying AnkiConnect")
            result = sync_from_ankiconnect(config, min_interval, log)
    else:
        result = sync_from_ankiconnect(config, min_interval, log)

    DATA.mkdir(exist_ok=True)
    KNOWN_PATH.write_text(json.dumps({
        "date": datetime.date.today().isoformat(), "min_interval": min_interval,
        "words": sorted(result["known_words"]), "kanji": sorted(result["known_kanji"]),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {"known_words": len(result["known_words"]), "known_kanji": len(result["known_kanji"])}
    if result["words"]:
        summary["lexicon"] = write_lexicon(result["words"])
    if result["kanji"]:
        KANJI_PATH.write_text(json.dumps(result["kanji"], ensure_ascii=False, indent=1), encoding="utf-8")
        summary["kanji_notes"] = len(result["kanji"])
    if result["grammar"]:
        GRAMMAR_PATH.write_text(json.dumps(result["grammar"], ensure_ascii=False, indent=1), encoding="utf-8")
        summary["grammar_points"] = len(result["grammar"])
    log(f"✓ {KNOWN_PATH}: {summary['known_words']} known word forms, {summary['known_kanji']} known kanji"
        + (f" · lexicon {summary['lexicon']} words" if "lexicon" in summary else "")
        + (f" · {summary['grammar_points']} grammar points" if "grammar_points" in summary else ""))
    return summary


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Reads the words, kanji and grammar you know in Anki.")
    p.add_argument("--min-interval", type=int, default=None,
                   help="minimum card interval in days (21 = mature, 0 = any reviewed card; default: data/anki.json or 21)")
    p.add_argument("--source", choices=["file", "ankiconnect"], default=None,
                   help="read the collection file (default, Anki can be closed) or go through AnkiConnect")
    p.add_argument("--setup", action="store_true", help="detect your note types and (re)write data/anki.json")
    p.add_argument("--collection", default=None, help="path to a collection.anki2 (default: your Anki profile)")
    p.add_argument("--profile", default=None, help="Anki profile name, if you have several")
    args = p.parse_args()

    if args.setup or args.collection or args.profile:
        import anki_db
        col = anki_db.AnkiCollection.open(args.collection, args.profile)
        try:
            config = setup_config(col, write=False)
        finally:
            col.close()
        config["collection_path"], config["profile"] = args.collection, args.profile
        DATA.mkdir(exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✓ {CONFIG_PATH} written. Note types found:")
        for name, layout in config["note_types"].items():
            detail = ", ".join(f"{k}: {v}" for k, v in layout.items() if k not in ("role", "notes") and v)
            print(f"  {name} ({layout['notes']} notes) → {layout['role']}" + (f"  [{detail}]" if detail else ""))
        print("Edit the file if a role or a field is wrong (role « ignore » skips a note type).")
        if args.setup:
            return
    try:
        sync(args.source, args.min_interval)
    except urllib.error.URLError:
        sys.exit("Cannot reach AnkiConnect on localhost:8765 (Anki must be open with the add-on), "
                 "or use the default --source file.")


if __name__ == "__main__":
    main()
