"""
The word card: what a click on a word of a sentence shows (like a jisho.org page, shorter).

    lookup("食べる") → {"word", "reading", "common", "jlpt", "senses": [{"pos", "en"}], "forms",
                        "deck": {...} | None, "kanji": [{"k", "meanings", "on", "kun", "jlpt", "grade",
                        "strokes", "known"}], "jisho_url", "online"}

Sources:
  - jisho.org's search API (JMdict, English), through this server, cached in data/dictionary.db so a word is
    asked once. If Jisho cannot be reached, the card still has the rest.
  - resources/kanji_info.json: KANJIDIC2 (EDRDG, CC BY-SA 4.0) through kanji-data by David Gouveia (MIT):
    strokes, school grade, JLPT level, meanings, on / kun readings of 3,000 common kanji. No network needed.
  - your Anki deck (data/lexicon.db, data/kanji.json, data/known.json): « in your deck », known or not.
"""

import json
import re
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

import lexicon

JISHO_API = "https://jisho.org/api/v1/search/words?keyword="
JISHO_PAGE = "https://jisho.org/search/"
CACHE_PATH = Path("data") / "dictionary.db"
KANJI = re.compile(r"[㐀-鿿々]")
RESOURCES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "resources"
_lock = threading.Lock()
_offline_until = [0.0]   # after a failure, do not wait for Jisho again for a few minutes


@lru_cache(maxsize=1)
def kanji_info() -> dict:
    path = RESOURCES / "kanji_info.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@lru_cache(maxsize=1)
def _anki_kanji(mtime: float) -> dict:
    path = Path("data") / "kanji.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def anki_kanji() -> dict:
    path = Path("data") / "kanji.json"
    return _anki_kanji(path.stat().st_mtime if path.exists() else 0)


@lru_cache(maxsize=1)
def _known(mtime: float) -> dict:
    path = Path("data") / "known.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"words": set(data.get("words", [])), "kanji": set(data.get("kanji", []))}


def known() -> dict:
    path = Path("data") / "known.json"
    return _known(path.stat().st_mtime if path.exists() else 0)


# ---------------------------------------------------------------------------
# Jisho, cached
# ---------------------------------------------------------------------------

def _cache():
    CACHE_PATH.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(CACHE_PATH)
    db.execute("CREATE TABLE IF NOT EXISTS jisho (word TEXT PRIMARY KEY, data TEXT, fetched TEXT)")
    return db


def jisho(word: str, timeout: float = 6) -> list:
    """Jisho's entries for a word (the API's « data » list); None if Jisho cannot be reached."""
    with _lock:
        db = _cache()
        try:
            row = db.execute("SELECT data FROM jisho WHERE word = ?", (word,)).fetchone()
        finally:
            db.close()
    if row:
        return json.loads(row[0])
    if time.time() < _offline_until[0]:
        return None
    try:
        request = urllib.request.Request(JISHO_API + urllib.parse.quote(word),
                                         headers={"User-Agent": "JapaneseCoach (study app)"})
        with urllib.request.urlopen(request, timeout=timeout) as r:
            entries = json.loads(r.read().decode("utf-8")).get("data", [])
    except Exception:
        _offline_until[0] = time.time() + 300
        return None
    with _lock:
        db = _cache()
        try:
            db.execute("INSERT OR REPLACE INTO jisho VALUES (?, ?, ?)",
                       (word, json.dumps(entries[:5], ensure_ascii=False), time.strftime("%Y-%m-%d")))
            db.commit()
        finally:
            db.close()
    return entries[:5]


def _best(entries: list, word: str):
    """The entry of the word itself (食べる, not 食べ物), else the first one."""
    for e in entries:
        for j in e.get("japanese", []):
            if j.get("word") == word or (not j.get("word") and j.get("reading") == word):
                return e
    return entries[0] if entries else None


SKIP_POS = {"Wikipedia definition", "Place", "Full name", "Other forms", "Notes"}


def _senses(entry: dict, limit: int = 5) -> list:
    out = []
    for s in entry.get("senses", []):
        pos = [p for p in s.get("parts_of_speech", []) if p not in SKIP_POS]
        if not s.get("english_definitions") or (s.get("parts_of_speech") and not pos and out):
            continue
        out.append({"pos": ", ".join(pos), "en": "; ".join(s["english_definitions"][:4]),
                    "info": "; ".join((s.get("tags") or []) + (s.get("info") or []))})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------

def kanji_card(k: str) -> dict:
    info = kanji_info().get(k, {})
    anki = anki_kanji().get(k, {})
    return {"k": k, "meanings": info.get("m") or [m.strip() for m in (anki.get("meaning") or "").split(";") if m.strip()][:4],
            "on": info.get("on") or anki.get("onyomi") or [], "kun": info.get("kun") or anki.get("kunyomi") or [],
            "jlpt": f"N{info['j']}" if info.get("j") else (anki.get("level") or ""), "grade": info.get("g"),
            "strokes": info.get("s"), "known": k in known()["kanji"] or bool(anki.get("known")),
            "in_deck": bool(anki), "jisho_url": JISHO_PAGE + urllib.parse.quote(k + " #kanji")}


def lookup(word: str, online: bool = True) -> dict:
    word = (word or "").strip()[:40]
    deck = lexicon.lookup(word) if lexicon.available() else None
    card = {"word": word, "reading": "", "common": False, "jlpt": "", "senses": [], "forms": [],
            "deck": None, "kanji": [], "jisho_url": JISHO_PAGE + urllib.parse.quote(word), "online": False}
    entries = jisho(word) if online and word else None
    entry = _best(entries or [], word)
    if entries is not None:
        card["online"] = True
    if entry:
        japanese = entry.get("japanese", [])
        main = next((j for j in japanese if j.get("word") == word), japanese[0] if japanese else {})
        card.update(word=main.get("word") or main.get("reading") or word, reading=main.get("reading", ""),
                    common=bool(entry.get("is_common")), senses=_senses(entry),
                    jlpt=", ".join(j.replace("jlpt-", "").upper() for j in entry.get("jlpt", [])[:1]),
                    forms=[j.get("word") or j.get("reading") for j in japanese[1:4]])
    if deck:
        card["deck"] = {"known": deck.get("known") or word in known()["words"], "meaning": deck.get("meaning", ""),
                        "level": deck.get("level", ""), "reading": deck.get("reading", "")}
        card["reading"] = card["reading"] or deck.get("reading", "")
        card["jlpt"] = card["jlpt"] or deck.get("level", "")
        if not card["senses"] and deck.get("meaning"):
            card["senses"] = [{"pos": "", "en": deck["meaning"], "info": ""}]
    elif word in known()["words"]:
        card["deck"] = {"known": True, "meaning": "", "level": "", "reading": ""}
    seen = []
    for c in card["word"] + ("" if card["word"] == word else word):
        if KANJI.match(c) and c not in seen:
            seen.append(c)
    card["kanji"] = [kanji_card(c) for c in seen[:6]]
    return card
