#!/usr/bin/env python3
"""
Builds the sentence bank from Tatoeba (real, translated sentences).

    python build_bank.py            # Japanese sentences with a French translation
    python build_bank.py --english  # + sentences that only have an English translation

Steps:
  1. download the Tatoeba exports into data/tatoeba/ (once);
  2. keep the Japanese sentences that have a translation;
  3. split each sentence with SudachiPy (words, part of speech, reading);
  4. store everything in data/bank.db (SQLite).

Dependencies: pip install -r requirements.txt
Data: Tatoeba (https://tatoeba.org), CC BY 2.0 FR licence.
"""

import argparse
import bz2
import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

DATA_DIR = Path("data")
TATOEBA_DIR = DATA_DIR / "tatoeba"
BANK_PATH = DATA_DIR / "bank.db"
BASE_URL = "https://downloads.tatoeba.org/exports/per_language"

FILES = {
    "jpn": f"{BASE_URL}/jpn/jpn_sentences.tsv.bz2",
    "fra": f"{BASE_URL}/fra/fra_sentences.tsv.bz2",
    "jpn-fra": f"{BASE_URL}/jpn/jpn-fra_links.tsv.bz2",
    "eng": f"{BASE_URL}/eng/eng_sentences.tsv.bz2",
    "jpn-eng": f"{BASE_URL}/jpn/jpn-eng_links.tsv.bz2",
}

# Parts of speech that are not counted as "words" (punctuation, spaces).
NON_WORDS = {"補助記号", "空白", "記号"}


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download(name: str) -> Path:
    url = FILES[name]
    path = TATOEBA_DIR / url.rsplit("/", 1)[1]
    if path.exists() and path.stat().st_size > 0:
        return path
    TATOEBA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"↓ {path.name}…", end="", flush=True)
    partial = path.with_suffix(".part")
    with urllib.request.urlopen(url, timeout=120) as response, open(partial, "wb") as f:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        while chunk := response.read(1 << 16):
            f.write(chunk)
            received += len(chunk)
            if total:
                print(f"\r↓ {path.name} {received * 100 // total:3d} %", end="", flush=True)
    partial.replace(path)
    print(f"\r↓ {path.name} ✓ ({received / 1e6:.1f} MB)      ")
    return path


def read_tsv(path: Path):
    with bz2.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield line.rstrip("\n").split("\t")


def read_sentences(path: Path, wanted_ids=None) -> dict:
    """File « id  lang  text » → {id: text}."""
    sentences = {}
    for fields in read_tsv(path):
        if len(fields) < 3:
            continue
        i = int(fields[0])
        if wanted_ids is None or i in wanted_ids:
            sentences[i] = fields[2]
    return sentences


def read_links(path: Path) -> dict:
    """File « japanese_id  translation_id » → {japanese_id: first translation_id}."""
    links = {}
    for fields in read_tsv(path):
        if len(fields) >= 2:
            links.setdefault(int(fields[0]), int(fields[1]))
    return links


# ---------------------------------------------------------------------------
# Morphological analysis
# ---------------------------------------------------------------------------

def make_analyzer():
    try:
        from sudachipy import Dictionary, SplitMode
    except ImportError:
        sys.exit("SudachiPy is not installed. Run: pip install -r requirements.txt")
    try:
        dictionary = Dictionary(dict="core")
    except TypeError:  # older SudachiPy versions
        dictionary = Dictionary(dict_type="core")
    # SudachiPy ≥ 0.7: tokenizer(); earlier versions: create()
    tokenizer = dictionary.tokenizer() if hasattr(dictionary, "tokenizer") else dictionary.create()
    return lambda text: tokenizer.tokenize(text, SplitMode.C)


def to_hiragana(text: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def analyze(analyzer, text: str) -> list:
    """Each token: [surface, part of speech, sub-category, reading in hiragana, dictionary form]."""
    tokens = []
    for m in analyzer(text):
        pos = m.part_of_speech()
        surface = m.surface()
        reading = m.reading_form() if pos[0] not in NON_WORDS else ""
        tokens.append([surface, pos[0], pos[1], to_hiragana(reading) or surface, m.dictionary_form()])
    return tokens


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Builds data/bank.db from Tatoeba.")
    p.add_argument("--english", action="store_true",
                   help="also keep sentences that only have an English translation (bigger download)")
    args = p.parse_args()

    analyzer = make_analyzer()  # check SudachiPy before downloading anything

    t0 = time.time()
    links_fr = read_links(download("jpn-fra"))
    links_en = read_links(download("jpn-eng")) if args.english else {}
    jp_ids = set(links_fr) | set(links_en)

    print("Reading sentences…")
    japanese = read_sentences(download("jpn"), jp_ids)
    french = read_sentences(download("fra"), set(links_fr.values()))
    english = read_sentences(download("eng"), set(links_en.values())) if args.english else {}

    DATA_DIR.mkdir(exist_ok=True)
    if BANK_PATH.exists():
        BANK_PATH.unlink()
    db = sqlite3.connect(BANK_PATH)
    db.execute("""CREATE TABLE sentences (
        id INTEGER PRIMARY KEY,   -- Tatoeba id of the Japanese sentence
        jp TEXT NOT NULL,
        fr TEXT,
        en TEXT,
        word_count INTEGER NOT NULL,
        tokens TEXT NOT NULL      -- JSON: [[surface, pos, sub-category, reading, dictionary form], …]
    )""")

    print(f"Analyzing {len(japanese)} sentences…")
    rows = []
    for n, (i, jp) in enumerate(japanese.items(), 1):
        fr = french.get(links_fr.get(i))
        en = english.get(links_en.get(i))
        if not (fr or en):
            continue
        tokens = analyze(analyzer, jp)
        word_count = sum(1 for t in tokens if t[1] not in NON_WORDS)
        rows.append((i, jp, fr, en, word_count, json.dumps(tokens, ensure_ascii=False)))
        if n % 5000 == 0:
            print(f"  {n}/{len(japanese)}")
    db.executemany("INSERT INTO sentences VALUES (?, ?, ?, ?, ?, ?)", rows)
    db.execute("CREATE INDEX idx_word_count ON sentences(word_count)")
    db.commit()
    db.close()

    with_fr = sum(1 for r in rows if r[2])
    print(f"✓ {BANK_PATH}: {len(rows)} sentences ({with_fr} with a French translation) "
          f"in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
