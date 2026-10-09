"""
Reliable references for the chat tutor (retrieval): before the LLM answers, we look up what the
student's message is about and give it real material to lean on instead of its memory:

  - grammar points of your Anki grammar deck (data/grammar.json: meaning, usage, example sentences);
  - the programme's grammar notes (curriculum.py);
  - words of the message in your lexicon (reading, meaning, JLPT level, known or not);
  - real example sentences from the Tatoeba bank with their French translation.

references(message, exercise) → (text for the LLM, short list shown under the answer)
"""

import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from coach import curriculum
from coach import lexicon
GRAMMAR_PATH = Path("data") / "grammar.json"
BANK_PATH = Path("data") / "bank.db"
JAPANESE_RUN = re.compile(r"[぀-ヿ㐀-鿿々ー]+")
CONTENT_POS = {"名詞", "動詞", "形容詞", "形状詞", "副詞"}


def grammar_points() -> list:
    return _grammar_points(GRAMMAR_PATH.stat().st_mtime if GRAMMAR_PATH.exists() else 0)


@lru_cache(maxsize=1)
def _grammar_points(mtime: float) -> list:
    """[(search keys, point)] — keys are the Japanese forms of the point without 〜 and brackets."""
    if not GRAMMAR_PATH.exists():
        return []
    points = []
    for g in json.loads(GRAMMAR_PATH.read_text(encoding="utf-8")):
        keys = set()
        for part in re.split(r"[/／、,・\n]| or ", g["point"]):
            key = re.sub(r"[〜～~\s（）()\[\]「」…]", "", part)
            key = re.sub(r"^(Verb|Noun|Adj|V|N|A)[-\w]*\+?", "", key)
            if JAPANESE_RUN.fullmatch(key or "-") and len(key) >= 2:
                keys.add(key)
        if keys:
            points.append((sorted(keys, key=len, reverse=True), g))
    return points


def find_grammar(text: str, limit: int = 3) -> list:
    found = []
    for keys, g in grammar_points():
        best = max((len(k) for k in keys if k in text), default=0)
        if best:
            found.append((best, g))
    found.sort(key=lambda x: -x[0])
    return [g for _, g in found[:limit]]


FORM_KEYS = {
    "masu": r"forme polie|ます形|〜ます", "negative": r"négatif|ない形|forme en ない", "past": r"passé|た形|forme en た",
    "te-form": r"forme en て|forme te\b|te-form|て形", "tai": r"たい", "volitional": r"volitif|意向形|〜よう",
    "nagara": r"ながら", "ba": r"conditionnel en ば|ば形|〜ば\b|ければ", "tara": r"たら",
    "causative": r"causatif|使役|させる", "noni-node": r"のに|ので",
}


def find_topics(text: str, exercise: dict = None) -> list:
    """Programme topics the message is about (the exercise's topic first)."""
    topics = []
    if exercise and exercise.get("topic") in curriculum.BY_TITLE:
        topics.append(curriculum.BY_TITLE[exercise["topic"]])
    for t in curriculum.TOPICS:
        if t in topics:
            continue
        if "targets" in t and t["id"] != "noni-node":
            marks = t["targets"].split(",")
            # both particles mentioned on their own, e.g. « に ou で ? »
            if all(re.search(rf"(?<![\u3040-\u30ff\u3400-\u9fff]){m}(?![\u3040-\u30ff\u3400-\u9fff])", text) for m in marks):
                topics.append(t)
        elif t["id"] in FORM_KEYS and re.search(FORM_KEYS[t["id"]], text, re.I):
            topics.append(t)
    return topics[:2]


def find_words(tokens: list, limit: int = 8) -> list:
    if not lexicon.available():
        return []
    out, seen = [], set()
    for t in tokens:
        if t[1] not in CONTENT_POS or t[2] in ("数詞", "固有名詞"):
            continue
        entry = lexicon.lookup(t[4]) or lexicon.lookup(t[0])
        if entry and entry["word"] not in seen:
            seen.add(entry["word"])
            out.append(entry)
    return out[:limit]


def find_sentences(terms: list, limit: int = 4, language: str = "fr") -> list:
    """Short real sentences containing one of the terms, with a translation (French or English)."""
    if not BANK_PATH.exists() or not terms:
        return []
    db = sqlite3.connect(BANK_PATH)
    out, seen = [], set()
    try:
        for term in terms:
            col = "en" if language == "en" else "fr"
            rows = db.execute(f"SELECT jp, {col} FROM sentences WHERE {col} IS NOT NULL AND jp LIKE ? "
                              "ORDER BY word_count LIMIT 3", (f"%{term}%",)).fetchall()
            for jp, fr in rows:
                if jp not in seen:
                    seen.add(jp)
                    out.append((jp, fr))
            if len(out) >= limit:
                break
    finally:
        db.close()
    return out[:limit]


def references(message: str, tokens: list = None, exercise: dict = None, language: str = "fr") -> tuple:
    """(text block for the LLM, short labels for the student). tokens: SudachiPy analysis of the message."""
    text = message + " " + json.dumps(exercise or {}, ensure_ascii=False)
    blocks, labels = [], []

    for g in find_grammar(text):
        block = f"• Point de grammaire {g['point']}" + (f" ({g['level']})" if g.get("level") else "")
        for field, name in (("meaning", "sens"), ("usage", "construction"), ("phrases", "exemples")):
            if g.get(field):
                block += f"\n  {name} : " + g[field].replace("\n", " | ")[:500]
        blocks.append(block)
        labels.append(("grammar " if language == "en" else "grammaire ") + g["point"])

    for t in find_topics(message, exercise):
        blocks.append(f"• Programme note « {curriculum.title(t['title'], 'en')} » ({t['level']}): {curriculum.note(t, 'en')}"
                      if language == "en" else f"• Fiche du programme « {t['title']} » ({t['level']}) : {t['note']}")
        labels.append(f"note « {curriculum.title(t['title'], 'en')} »" if language == "en" else f"fiche « {t['title']} »")

    words = find_words(tokens or [])
    if words:
        blocks.append("• Vocabulaire du message :\n" + "\n".join(
            f"  {w['word']}" + (f" ({w['reading']})" if w['reading'] and w['reading'] != w['word'] else "")
            + f" : {w['meaning'] or '?'}" + (f" [{w['level']}]" if w['level'] else "")
            + (" — connu de l'élève" if w['known'] else "") for w in words))
        labels.append(f"{len(words)} word(s) from the lexicon" if language == "en" else f"{len(words)} mot(s) du lexique")

    terms = [k for keys, _ in grammar_points() for k in keys[:1] if k in text][:3]
    terms += [w["word"] for w in words if not w["known"]][:2]
    terms += [m for m in JAPANESE_RUN.findall(message) if 2 <= len(m) <= 6][:2]
    sentences = find_sentences(list(dict.fromkeys(terms)), language=language)
    if sentences:
        blocks.append("• Phrases réelles (corpus Tatoeba) utilisables comme exemples :\n"
                      + "\n".join(f"  {jp} — {fr}" for jp, fr in sentences))
        labels.append(f"{len(sentences)} Tatoeba sentence(s)" if language == "en" else f"{len(sentences)} phrase(s) Tatoeba")

    if not blocks:
        return "", []
    header = ("[Reliable references — rely on them, do not contradict them, and prefer reusing these real sentences "
              "as examples rather than inventing new ones]\n") if language == "en" else (
              "[Références fiables — appuie-toi dessus, ne les contredis pas, et réutilise de préférence ces phrases "
              "réelles comme exemples plutôt que d'en inventer]\n")
    return header + "\n".join(blocks), labels
