#!/usr/bin/env python3
"""
JLPT-style multiple-choice questions built from real sentences (data/bank.db), by level.

    python jlpt_questions.py --level N4                      # 10 new questions of each type
    python jlpt_questions.py --level N5 --types kanji_reading,ordering --count 20
    python jlpt_questions.py --level N4 --no-llm             # instant (types that need a check are skipped)

Question types (the « connaissances de la langue » part of the test):
  kanji_reading  漢字読み   how is the underlined word read?        distractors: long/short vowel, っ, voicing…
  orthography    表記       which kanji spelling for the word in kana?  distractors: kanji with the same on'yomi
  vocab          文脈規定   which word fits the blank?              distractors: words of the same level, LLM check
  grammar        文法形式   which particle / verb form fits?        distractors: confusable particles, other forms, LLM check
  ordering       並べ替え ★ which piece goes at ★?                  the sentence's own pieces, shuffled

The level of a question = the JLPT level of its words (data/lexicon.db, from anki_sync.py and jlpt_data.py).
Questions go to the app's reserve under the topics « JLPT N4 · … ».
"""

import argparse
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

import conjugate
import lexicon
import llm
import make_exercises as mx
import store
from sheet import BLANK, normalize

BANK_PATH = Path("data") / "bank.db"
KANJI_PATH = Path("data") / "kanji.json"

TYPES = ["kanji_reading", "orthography", "vocab", "grammar", "ordering"]
LABELS = {
    "kanji_reading": "漢字読み (lecture)",
    "orthography": "表記 (écriture)",
    "vocab": "文脈規定 (vocabulaire)",
    "grammar": "文法形式 (grammaire)",
    "ordering": "並べ替え ★ (ordre)",
}
NEEDS_LLM = {"vocab", "grammar"}
# Mock exam: number of questions per type (inspired by the real test, without reading comprehension).
EXAM = {
    "N5": {"kanji_reading": 7, "orthography": 5, "vocab": 6, "grammar": 9, "ordering": 4},
    "N4": {"kanji_reading": 7, "orthography": 5, "vocab": 8, "grammar": 13, "ordering": 4},
    "N3": {"kanji_reading": 8, "orthography": 6, "vocab": 11, "grammar": 13, "ordering": 5},
    "N2": {"kanji_reading": 5, "orthography": 5, "vocab": 7, "grammar": 12, "ordering": 5},
    "N1": {"kanji_reading": 6, "orthography": 0, "vocab": 7, "grammar": 10, "ordering": 5},
}
MAX_WORDS = {"N5": 10, "N4": 12, "N3": 15, "N2": 18, "N1": 20}

CONTENT_POS = {"名詞", "動詞", "形容詞", "形状詞", "副詞"}
SKIP_SUB = {"数詞", "固有名詞", "非自立可能"}
KANJI = re.compile(r"[㐀-鿿々]")
PARTICLES = ["は", "が", "を", "に", "で", "へ", "と", "も", "から", "まで", "より", "や"]
CONFUSABLE = {
    "に": ["で", "へ", "を", "が"], "で": ["に", "を", "が", "へ"], "は": ["が", "を", "も", "に"],
    "が": ["は", "を", "に", "も"], "を": ["が", "に", "で", "は"], "へ": ["に", "で", "を", "が"],
    "と": ["や", "に", "で", "も"], "も": ["は", "が", "を", "に"], "から": ["まで", "より", "で", "に"],
    "まで": ["から", "に", "で", "より"], "より": ["から", "まで", "で", "に"], "や": ["と", "も", "に", "か"],
}
GRAMMAR_FORMS = ["masu", "te", "past", "negative", "tai", "volitional", "ba", "tara", "causative"]


def topic_title(level: str, qtype: str) -> str:
    return f"JLPT {level} · {LABELS[qtype]}"


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

def word_level(t: list) -> str:
    for form in (t[4], t[0]):
        lvl = lexicon.level(form)
        if lvl:
            return lvl
    return ""


def sentence_fits(tokens: list, level: str) -> bool:
    """Every content word at the level or easier (one unlisted word allowed)."""
    if not lexicon.available():
        return True
    top, unlisted = lexicon.level_rank(level), 0
    for t in tokens:
        if t[1] not in CONTENT_POS or t[2] in SKIP_SUB or (len(t) > 5 and t[5] in SKIP_SUB):
            continue
        rank = lexicon.level_rank(word_level(t))
        if rank == 5:
            unlisted += 1
        elif rank > top:
            return False
    return unlisted <= 1


def target_words(tokens: list, level: str) -> list:
    """Indexes of kanji nouns / na-adjectives of exactly this level (the words a question can test)."""
    out = []
    for k, t in enumerate(tokens):
        if t[1] in ("名詞", "形状詞") and t[2] not in SKIP_SUB and KANJI.search(t[0]) and t[0] == t[4]:
            if not lexicon.available() or word_level(t) == level:
                out.append(k)
    return out


# ---------------------------------------------------------------------------
# Distractors
# ---------------------------------------------------------------------------

DAKUTEN = dict(zip("かきくけこさしすせそたちつてとはひふへほ", "がぎぐげござじずぜぞだぢづでどばびぶべぼ"))
DAKUTEN.update({v: k for k, v in list(DAKUTEN.items())})
HANDAKUTEN = dict(zip("はひふへほばびぶべぼ", "ぱぴぷぺぽぱぴぷぺぽ"))
O_ROW = set("おこごそぞとどのほぼぽもよろょ")
E_ROW = set("えけげせぜてでねへべぺめれ")
SMALL = {"ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "や": "ゃ", "ゆ": "ゅ", "よ": "ょ"}
SOKUON_BEFORE = set("かきくけこさしすせそたちつてとぱぴぷぺぽ")


def reading_variants(reading: str) -> list:
    """Plausible wrong readings: long/short vowels, っ, voicing, small ゃゅょ."""
    out = []
    r = reading
    for i, c in enumerate(r):
        if c in "うい" and i > 0 and (r[i - 1] in O_ROW or r[i - 1] in E_ROW):
            out.append(r[:i] + r[i + 1:])                     # こう → こ
        if c in O_ROW and (i + 1 == len(r) or r[i + 1] != "う"):
            out.append(r[:i + 1] + "う" + r[i + 1:])          # こ → こう
        if c == "っ":
            out.append(r[:i] + r[i + 1:])                     # がっこう → がこう
        if c in SOKUON_BEFORE and i > 0 and r[i - 1] not in "っん":
            out.append(r[:i] + "っ" + r[i:])                  # かこ → かっこ
        if c in DAKUTEN:
            out.append(r[:i] + DAKUTEN[c] + r[i + 1:])        # か ↔ が
        if c in HANDAKUTEN and i == 0:
            out.append(HANDAKUTEN[c] + r[1:])
        if c in "ゃゅょ":
            out.append(r[:i] + SMALL[c] + r[i + 1:])          # きょ → きよ
        elif c in "やゆよ" and i > 0 and r[i - 1] in "きぎしじちにひびぴみり":
            out.append(r[:i] + SMALL[c] + r[i + 1:])          # きよ → きょ
    return list(dict.fromkeys(v for v in out if v and v != reading))


_homophones, _homophones_mtime = None, None


def homophones() -> dict:
    """{kanji: [other kanji sharing an on'yomi]} from data/kanji.json (Anki kanji notes)."""
    global _homophones, _homophones_mtime
    mtime = KANJI_PATH.stat().st_mtime if KANJI_PATH.exists() else 0
    if _homophones is None or mtime != _homophones_mtime:
        _homophones, _homophones_mtime = {}, mtime
        _noun_pool.clear()
        if KANJI_PATH.exists():
            data = json.loads(KANJI_PATH.read_text(encoding="utf-8"))
            by_on = {}
            for k, info in data.items():
                for on in info.get("onyomi", []):
                    by_on.setdefault(on.replace("-", ""), set()).add(k)
            for k, info in data.items():
                same = set()
                for on in info.get("onyomi", []):
                    same |= by_on.get(on.replace("-", ""), set())
                _homophones[k] = sorted(same - {k})
    return _homophones


def spelling_variants(word: str, rng: random.Random) -> list:
    out = []
    for i, c in enumerate(word):
        for other in homophones().get(c, []):
            out.append(word[:i] + other + word[i + 1:])
    rng.shuffle(out)
    return list(dict.fromkeys(v for v in out if v != word))


def valid_readings(word: str) -> set:
    entry = lexicon.lookup(word)
    return {entry["reading"]} if entry and entry["reading"] else set()


# ---------------------------------------------------------------------------
# Question builders — each returns a question dict or None
# ---------------------------------------------------------------------------

def base(id_: int, jp: str, fr: str, qtype: str, level: str, answer: str) -> dict:
    return {"qtype": qtype, "level": level, "full_sentence": jp, "translation": fr or "",
            "show_translation": qtype in NEEDS_LLM, "hint": "", "explanation": "",
            "source": f"Tatoeba #{id_}", "source_url": f"https://tatoeba.org/fr/sentences/show/{id_}",
            "key": f"tatoeba:{id_}:jlpt-{qtype}:{answer}"}


def with_choices(q: dict, answer: str, distractors: list, rng: random.Random) -> dict:
    choices = [answer] + distractors[:3]
    rng.shuffle(choices)
    q.update(choices=choices, answers=[answer], answer_index=choices.index(answer))
    return q


def q_kanji_reading(id_, jp, fr, tokens, level, rng):
    for k in target_words(tokens, level):
        t = tokens[k]
        wrong = [v for v in reading_variants(t[3]) if v not in valid_readings(t[0])]
        if len(wrong) < 3:
            continue
        rng.shuffle(wrong)
        q = base(id_, jp, fr, "kanji_reading", level, t[3])
        q["question"] = "".join(x[0] for x in tokens[:k]) + f"【{t[0]}】" + "".join(x[0] for x in tokens[k + 1:])
        q["explanation"] = f"{t[0]} se lit {t[3]}." + (f" ({lexicon.lookup(t[0])['meaning']})" if lexicon.lookup(t[0]) else "")
        return with_choices(q, t[3], wrong, rng)
    return None


def q_orthography(id_, jp, fr, tokens, level, rng):
    if not homophones():
        return None
    for k in target_words(tokens, level):
        t = tokens[k]
        wrong = spelling_variants(t[0], rng)
        if len(wrong) < 3:
            continue
        q = base(id_, jp, fr, "orthography", level, t[0])
        q["question"] = "".join(x[0] for x in tokens[:k]) + f"【{t[3]}】" + "".join(x[0] for x in tokens[k + 1:])
        q["explanation"] = f"{t[3]} s'écrit {t[0]}." + (f" ({lexicon.lookup(t[0])['meaning']})" if lexicon.lookup(t[0]) else "")
        return with_choices(q, t[0], wrong, rng)
    return None


_noun_pool = {}


def noun_pool(level: str) -> list:
    key = (level, lexicon._mtime())
    if key not in _noun_pool:
        _noun_pool[key] = [w["word"] for w in lexicon.words(level)
                             if len(w["word"]) <= 4 and all(KANJI.match(c) for c in w["word"])] if lexicon.available() else []
    return _noun_pool[key]


def q_vocab(id_, jp, fr, tokens, level, rng):
    pool = noun_pool(level)
    for k in target_words(tokens, level):
        t = tokens[k]
        if t[1] != "名詞" or len(pool) < 10:
            continue
        wrong = [w for w in rng.sample(pool, min(12, len(pool))) if w != t[0] and w not in t[0]][:3]
        if len(wrong) < 3:
            continue
        q = base(id_, jp, fr, "vocab", level, t[0])
        q["question"] = "".join(x[0] for x in tokens[:k]) + "（　　）" + "".join(x[0] for x in tokens[k + 1:])
        q["sentence"] = "".join(x[0] for x in tokens[:k]) + BLANK + "".join(x[0] for x in tokens[k + 1:])
        return with_choices(q, t[0], wrong, rng)
    return None


def q_grammar(id_, jp, fr, tokens, level, rng):
    # A verb form, one time out of two when the sentence has one; otherwise a particle.
    if rng.random() < 0.5:
        for form in rng.sample(GRAMMAR_FORMS, len(GRAMMAR_FORMS)):
            spans = mx.conjugation_blanks(tokens, form) if form in mx.FORMS else []
            if not spans:
                continue
            a, b = spans[0]
            verb = tokens[a]
            conj_type = verb[6] if len(verb) > 6 else ""
            answer = "".join(x[0] for x in tokens[a:b])
            others = [conjugate.conjugate(verb[4], f, conj_type) for f in GRAMMAR_FORMS if f != form]
            wrong = [o for o in dict.fromkeys(others) if o and o != answer]
            if not conjugate.verb_class(verb[4], conj_type) or len(wrong) < 3:
                continue
            rng.shuffle(wrong)
            q = base(id_, jp, fr, "grammar", level, answer)
            before = "".join(x[0] for x in tokens[:a])
            after = "".join(x[0] for x in tokens[b:])
            q.update(question=before + "（　　）" + after, sentence=before + BLANK + after, form=form)
            return with_choices(q, answer, wrong, rng)
    spots = [k for k, t in enumerate(tokens) if t[0] in PARTICLES and t[1] == "助詞"
             and t[2] in ("格助詞", "係助詞", "副助詞") and mx.simple_particle_context(tokens, k)]
    if not spots:
        return None
    k = rng.choice(spots)
    answer = tokens[k][0]
    wrong = [p for p in CONFUSABLE.get(answer, []) if p != answer][:3]
    q = base(id_, jp, fr, "grammar", level, answer)
    before = "".join(x[0] for x in tokens[:k])
    after = "".join(x[0] for x in tokens[k + 1:])
    q.update(question=before + "（　　）" + after, sentence=before + BLANK + after)
    return with_choices(q, answer, wrong, rng)


def chunks(tokens: list) -> list:
    """Splits a sentence into pieces (bunsetsu-like): content word(s) + the particles / endings after them."""
    pieces, current = [], []
    for k, t in enumerate(tokens):
        starts = t[1] in ("名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "接続詞", "感動詞", "接頭辞")
        joins = bool(current) and (
            (t[1] == "名詞" and current[-1][1] in ("名詞", "接頭辞")                        # compound nouns
             and not (len(current[-1]) > 5 and current[-1][5] == "副詞可能"))            # but not 毎朝 + 駅
            or (t[1] == "動詞" and t[2] == "非自立可能" and current[-1][0] in ("て", "で"))  # 食べて + いる
            or (t[1] == "動詞" and t[4] in ("する", "為る") and current[-1][1] == "名詞")  # 勉強 + する
            or current[-1][1] == "接頭辞")
        if starts and current and not joins:
            pieces.append(current)
            current = []
        current.append(t)
    if current:
        pieces.append(current)
    return ["".join(x[0] for x in p) for p in pieces]


def q_ordering(id_, jp, fr, tokens, level, rng):
    parts = chunks(tokens)
    if len(parts) < 5:
        return None
    # four consecutive pieces, never the last one (it carries the end of the sentence)
    start = rng.randint(0, len(parts) - 5)
    four = parts[start:start + 4]
    if len(set(four)) < 4 or any(len(p) > 9 or not re.search(r"[぀-鿿]", p) for p in four):
        return None
    endings = [p[-1] for p in four]
    if len(set(endings)) < 4 and any(e in "はがをにでへとも" for e in endings):
        return None  # two pieces ending with the same particle could swap places
    star = four[2]
    order = four[:]
    rng.shuffle(order)
    q = base(id_, jp, fr, "ordering", level, star)
    before = "".join(parts[:start])
    after = "".join(parts[start + 4:])
    q["question"] = f"{before}＿＿ ＿＿ ★ ＿＿{after}"
    q.update(choices=order, answers=[star], answer_index=order.index(star),
             explanation="Ordre : " + " → ".join(four) + f"\n★ = {star}")
    return q


BUILDERS = {"kanji_reading": q_kanji_reading, "orthography": q_orthography, "vocab": q_vocab,
            "grammar": q_grammar, "ordering": q_ordering}


# ---------------------------------------------------------------------------
# LLM check for questions where another choice might also work
# ---------------------------------------------------------------------------

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "alternatives": {"type": "array", "items": {"type": "object", "properties": {
            "answer": {"type": "string"}, "correct": {"type": "boolean"}}, "required": ["answer", "correct"]}},
        "good_example": {"type": "boolean"},
        "problem": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["alternatives", "good_example", "problem", "explanation"],
}


def check(q: dict, model: str) -> tuple:
    answer = q["answers"][0]
    others = [c for c in q["choices"] if c != answer]
    listed = "\n".join(f"   - « {c} » → {q['sentence'].replace(BLANK, c)}" for c in others)
    what = "word" if q["qtype"] == "vocab" else "grammatical form"
    prompt = f"""JLPT {q['level']} multiple-choice question built from a real sentence (Tatoeba):
{q['sentence']}
Original sentence: {q['full_sentence']}
Translation: {q['translation']}
Expected answer: « {answer} ».

1. "alternatives": the same sentence with each OTHER choice in the blank:
{listed}
   For each, say in "correct" whether that exact sentence is grammatical, natural AND faithful to the translation.
   Be demanding: awkward, rare, or meaning-changing sentences are NOT correct.
2. "good_example": true if this is a fair JLPT {q['level']} question on the {what} « {answer} » (not an idiom, not far above the level).
   "problem": if false, a few words in English; otherwise "".
3. "explanation": in 1 to 3 sentences in French, why « {answer} » is right and the others are not."""
    messages = [{"role": "system", "content": mx.SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    try:
        result = llm.ask_json(model, messages, CHECK_SCHEMA)
    except (ValueError, json.JSONDecodeError):
        return False, "unreadable answer"
    for alt in result.get("alternatives", []) or []:
        if isinstance(alt, dict) and alt.get("answer") in others and alt.get("correct") is True:
            return False, f"« {alt['answer']} » judged correct too"
    if result.get("good_example") is False:
        return False, f"not a good example: {result.get('problem', '?')}"
    q["explanation"] = str(result.get("explanation", "")).strip()
    return True, ""


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def candidates(level: str, seed=None) -> list:
    if not BANK_PATH.exists():
        raise mx.GenerationError("Bank not found. Run first: python build_bank.py")
    db = sqlite3.connect(BANK_PATH)
    rows = db.execute("SELECT id, jp, fr, en, tokens FROM sentences WHERE word_count BETWEEN 3 AND ? AND fr IS NOT NULL",
                      (MAX_WORDS.get(level, 12),)).fetchall()
    db.close()
    rng = random.Random(seed)
    rng.shuffle(rows)
    return rows


def generate(level: str, qtype: str, count: int, model: str = llm.DEFAULT_MODEL, no_llm: bool = False,
             skip_keys=frozenset(), seed=None, log=print, should_stop=lambda: False, rows=None) -> list:
    if qtype in NEEDS_LLM and no_llm:
        log(f"  {LABELS[qtype]}: skipped (needs the LLM check)")
        return []
    rng = random.Random(seed)
    made, dropped, used = [], 0, set()
    for id_, jp, fr, en, tokens_json in rows if rows is not None else candidates(level, seed):
        if len(made) >= count or dropped > count * 4 or should_stop():
            break
        tokens = json.loads(tokens_json)
        if not sentence_fits(tokens, level):
            continue
        q = BUILDERS[qtype](id_, jp, fr, tokens, level, rng)
        if not q or q["key"] in skip_keys or q["answers"][0] in used:
            continue
        if qtype in NEEDS_LLM:
            try:
                ok, reason = check(q, model)
            except llm.OllamaUnavailable:
                raise mx.GenerationError("Cannot reach Ollama on localhost:11434. Start Ollama, or use --no-llm.")
            if not ok:
                dropped += 1
                log(f"  ✗ {q['question']}  ({reason})")
                continue
        used.add(q["answers"][0])  # vary the tested words
        made.append(q)
        log(f"  ✓ {len(made)}/{count}  {q['question']}")
    return made


def fill(db, level: str, per_type: int = 10, types: list = None, model: str = llm.DEFAULT_MODEL,
         no_llm: bool = False, log=print, should_stop=lambda: False) -> int:
    """Tops up each JLPT question type of the level to `per_type` unseen questions. Returns how many were added."""
    unseen = {t["topic"]: t["unseen"] for t in store.topics(db)}
    rows = candidates(level)
    added = 0
    for qtype in types or TYPES:
        title = topic_title(level, qtype)
        need = per_type - unseen.get(title, 0)
        if need <= 0 or should_stop():
            continue
        log(f"\n=== {title}: {need} question(s) ===")
        try:
            made = generate(level, qtype, need, model, no_llm, store.existing_keys(db), log=log,
                            should_stop=should_stop, rows=rows)
        except mx.GenerationError as e:
            log(f"  ! {e}")
            break
        for q in made:
            key = q.pop("key")
            added += store.add_exercise(db, title, "jlpt", q, key)
        log(f"  → {len(made)} added" + ("" if made or qtype in NEEDS_LLM and no_llm else
                                        " (no suitable sentence: is data/lexicon.db / data/kanji.json filled?)"))
    return added


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="JLPT-style questions from real sentences, into the app's reserve.")
    p.add_argument("--level", default="N4", choices=list(EXAM))
    p.add_argument("--types", default="", help=f"comma-separated, among: {', '.join(TYPES)} (default: all)")
    p.add_argument("--count", type=int, default=10, help="unseen questions wanted per type (default: 10)")
    p.add_argument("--model", default=llm.DEFAULT_MODEL)
    p.add_argument("--no-llm", action="store_true", help="skip the types that need the LLM check")
    args = p.parse_args()
    types = [t.strip() for t in args.types.split(",") if t.strip()] or TYPES
    bad = [t for t in types if t not in TYPES]
    if bad:
        sys.exit(f"Unknown type(s): {', '.join(bad)}")
    if not lexicon.available():
        print("  (no data/lexicon.db: levels are not checked — run anki_sync.py and/or jlpt_data.py)")
    added = fill(store.connect(), args.level, args.count, types, args.model, args.no_llm)
    print(f"\n✓ {added} JLPT {args.level} question(s) added. Open the app: python server.py")


if __name__ == "__main__":
    main()
