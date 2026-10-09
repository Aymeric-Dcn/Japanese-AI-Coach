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
import words
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
LABELS_EN = {
    "kanji_reading": "漢字読み (reading)",
    "orthography": "表記 (writing)",
    "vocab": "文脈規定 (vocabulary)",
    "grammar": "文法形式 (grammar)",
    "ordering": "並べ替え ★ (word order)",
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
VERSION = 2   # questions made by an older generator are replaced (review.revalidate)
MAX_WORDS = {"N5": 10, "N4": 12, "N3": 15, "N2": 18, "N1": 20}
ORDERING_EXTRA_WORDS = 8   # 並べ替え needs longer sentences (four pieces + context)

CONTENT_POS = {"名詞", "動詞", "形容詞", "形状詞", "副詞"}
SKIP_SUB = {"数詞", "固有名詞", "非自立可能"}
KANJI = re.compile(r"[㐀-鿿々]")
PARTICLES = ["は", "が", "を", "に", "で", "へ", "と", "も", "から", "まで", "より", "や"]
# Wrong choices for each particle. Pairs that are often BOTH correct are never offered together:
# は/が, は/も, に/へ, と/や, まで/に, から/より — without context, the student could not know.
CONFUSABLE = {
    "に": ["で", "を", "が", "と"], "で": ["に", "を", "が", "と"], "は": ["を", "に", "で", "と"],
    "が": ["を", "に", "で", "と"], "を": ["に", "で", "と", "が"], "へ": ["を", "で", "が", "と"],
    "と": ["に", "を", "で", "が"], "も": ["を", "に", "で", "と"], "から": ["まで", "を", "で", "に"],
    "まで": ["から", "を", "が", "で"], "より": ["まで", "を", "で", "が"], "や": ["を", "に", "で", "が"],
}
# Verbs taking both に and と (友達に/と会う), or both に and から (先生に/から習う).
TO_VERBS = {"会う", "話す", "相談", "結婚", "似る", "約束", "喧嘩", "けんか", "電話", "別れる", "遊ぶ", "付き合う"}
KARA_VERBS = {"習う", "もらう", "貰う", "借りる", "聞く", "教わる", "頂く", "いただく", "受ける"}
# Verbs taking both を and が (日本語を/が話せる, 水を/が飲みたい): potential forms and たい are checked separately.
TE_AUXILIARIES = {"いる", "居る", "ある", "有る", "おく", "置く", "しまう", "仕舞う", "みる", "見る", "くれる", "呉れる",
                  "もらう", "貰う", "あげる", "上げる", "くださる", "下さる", "いく", "行く", "くる", "来る", "ほしい", "欲しい"}
# No volitional: 行こう / 行きたい / 行かない と思う are all right, and it is mostly followed by と思う.
GRAMMAR_FORMS = ["masu", "te", "past", "negative", "tai", "ba", "tara", "causative"]


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
    """Indexes of kanji nouns / na-adjectives of exactly this level (the words a question can test).
    Skips words normally written in kana (事, 為…) and words that appear twice in the sentence."""
    out = []
    surfaces = [t[0] for t in tokens]
    for k, t in enumerate(tokens):
        if t[1] in ("名詞", "形状詞") and t[2] not in SKIP_SUB and KANJI.search(t[0]) and t[0] == t[4]:
            if lexicon.available() and (word_level(t) != level or lexicon.usually_kana(t[0])):
                continue
            if (len(t) > 5 and t[5] == "助数詞可能") or (k and tokens[k - 1][2] == "数詞"):
                continue   # counters (3月, 5人): too easy
            rest = "".join(surfaces[:k] + surfaces[k + 1:])
            if t[0] in rest or any(c in rest for c in t[0] if len(t[0]) == 1):
                continue   # 一月は…月です: the answer would be visible elsewhere
            out.append(k)
    return out


def meaning_of(word: str) -> str:
    entry = lexicon.lookup(word)
    return f" ({entry['meaning']})" if entry and entry.get("meaning") else ""


# ---------------------------------------------------------------------------
# Distractors
# ---------------------------------------------------------------------------

DAKUTEN = dict(zip("かきくけこさしすせそたちつてとはひふへほ", "がぎぐげござじずぜぞだぢづでどばびぶべぼ"))
DAKUTEN.update({v: k for k, v in list(DAKUTEN.items())})
HANDAKUTEN = dict(zip("はひふへほばびぶべぼ", "ぱぴぷぺぽぱぴぷぺぽ"))
O_ROW = set("おこごそぞとどのほぼぽもよろょ")
U_ROW = set("うくぐすずつづぬふぶぷむゆるゅ")
E_ROW = set("えけげせぜてでねへべぺめれ")
SMALL = {"ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "や": "ゃ", "ゆ": "ゅ", "よ": "ょ"}
GEMINATE_BEFORE = set("かきくけこさしすせそたちつてとぱぴぷぺぽ")   # っ only before these
GEMINATE_ENDS = set("つくちき")                                      # 学 がく + 校 こう → がっこう
NOT_FIRST = set("ぢづっんゃゅょー")


def to_hiragana(text: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


_kanji_readings, _kanji_mtime = {}, None


def kanji_data() -> dict:
    global _kanji_readings, _kanji_mtime
    mtime = KANJI_PATH.stat().st_mtime if KANJI_PATH.exists() else 0
    if mtime != _kanji_mtime:
        _kanji_mtime = mtime
        _homophones.clear()
        _noun_pool.clear()
        _kanji_readings = json.loads(KANJI_PATH.read_text(encoding="utf-8")) if KANJI_PATH.exists() else {}
    return _kanji_readings


def kanji_readings(c: str, on_only: bool = False) -> list:
    """Readings of a kanji in hiragana: on'yomi (コウ → こう) and kun'yomi stems (とお.る → とお)."""
    info = kanji_data().get(c) or {}
    out = [to_hiragana(r.replace("-", "")) for r in info.get("onyomi", [])]
    if not on_only:
        out += [r.replace("-", "").split(".")[0] for r in info.get("kunyomi", [])]
    return list(dict.fromkeys(r for r in out if r))


def kanji_level_ok(c: str) -> bool:
    info = kanji_data().get(c) or {}
    return info.get("known") or info.get("level") in ("N5", "N4", "N3")


def _shapes(r: str, first: bool, last: bool) -> list:
    """A kanji reading as it can appear in a word: as is, voiced (rendaku), or ending in っ."""
    shapes = [r]
    if not first and r[0] in DAKUTEN and r[0] not in "がぎぐげござじずぜぞだぢづでどばびぶべぼ":
        shapes.append(DAKUTEN[r[0]] + r[1:])
    if not first and r[0] in HANDAKUTEN:
        shapes.append(HANDAKUTEN[r[0]] + r[1:])
    if not last and len(r) > 1 and r[-1] in GEMINATE_ENDS:
        shapes.append(r[:-1] + "っ")
    return shapes


def split_reading(word: str, reading: str, detail: bool = False) -> list:
    """[(character, its part of the reading)] — 交通/こうつう → [(交, こう), (通, つう)]; None if no match.
    detail=True: [(character, part, base reading, is an on'yomi)] — 学/がっ → (学, がっ, がく, True)."""
    def walk(i, pos):
        if i == len(word):
            return [] if pos == len(reading) else None
        c = word[i]
        if not KANJI.match(c):
            if reading.startswith(to_hiragana(c), pos):
                rest = walk(i + 1, pos + 1)
                return None if rest is None else [(c, to_hiragana(c), to_hiragana(c), False)] + rest
            return None
        source = word[i - 1] if c == "々" and i else c
        on = set(kanji_readings(source, on_only=True))
        options = kanji_readings(source)
        for r in sorted(options, key=len, reverse=True):
            for shape in _shapes(r, i == 0, i == len(word) - 1):
                if reading.startswith(shape, pos):
                    rest = walk(i + 1, pos + len(shape))
                    if rest is not None:
                        return [(c, shape, r, r in on)] + rest
        return None
    if not word or not reading:
        return None
    parts = walk(0, 0)
    if parts is None or detail:
        return parts
    return [(p[0], p[1]) for p in parts]


def plausible(reading: str) -> bool:
    if not reading or reading[0] in NOT_FIRST or reading.endswith("っ") or "っっ" in reading:
        return False
    return all(reading[i + 1] in GEMINATE_BEFORE for i, c in enumerate(reading[:-1]) if c == "っ")


def _long_short(seg: str) -> list:
    if len(seg) >= 2 and seg[-1] == "お" and seg[-2] in O_ROW:
        return []                               # とお (通り) is already long: no とおう
    if len(seg) >= 2 and seg[-1] == "う" and (seg[-2] in O_ROW or seg[-2] in U_ROW):
        return [seg[:-1]]                       # こう → こ, つう → つ
    if len(seg) >= 2 and seg[-1] == "い" and seg[-2] in E_ROW:
        return [seg[:-1]]                       # せい → せ
    if seg[-1] in O_ROW or seg[-1] == "ゅ":
        return [seg + "う"]                     # こ → こう, しゅ → しゅう
    if seg[-1] in E_ROW:
        return [seg + "い"]
    return []


def reading_variants(reading: str, word: str = "") -> list:
    """Plausible wrong readings, one family at a time, like the real test:
    another reading of one of the kanji, long ↔ short vowel, voiced ↔ unvoiced, っ ↔ つ/く, ゅ ↔ ゆ.
    Returns [(family, wrong reading)]."""
    parts = split_reading(word, reading, detail=True) if word else None
    if not parts:
        parts = [(word or reading, reading, reading, False)]
    all_on = all(p[3] for p in parts if KANJI.match(p[0]))
    out = []

    def add(family, i, seg):
        new = "".join(seg if j == i else p[1] for j, p in enumerate(parts))
        if new != reading and plausible(new):
            out.append((family, new))

    for i, (c, seg, base_reading, is_on) in enumerate(parts):
        if not seg:
            continue
        # another on'yomi of the kanji: only in on'yomi compounds (交通 → こうつ), or for a lone kanji (光 → こう);
        # in 売り場 or 親切, other readings look silly (ばいりば, おやせつ)
        if KANJI.match(c) and (all_on or len(parts) == 1):
            for r in kanji_readings(c, on_only=True):
                for shape in _shapes(r, i == 0, i == len(parts) - 1)[:1]:
                    if shape != seg and abs(len(shape) - len(seg)) <= 2:
                        add("other", i, shape)
        for v in _long_short(seg):
            if len(v) < len(seg) or is_on:   # no long vowel added to a kun'yomi (気持ち → きもうち)
                add("long", i, v)
        if seg[0] in DAKUTEN and DAKUTEN[seg[0]] not in "ぢづ" and (i > 0 or seg[0] in "かきくけこさしすせそたちつてとはひふへほ"):
            add("voice", i, DAKUTEN[seg[0]] + seg[1:])
        if seg[-1] == "っ":
            add("geminate", i, seg[:-1] + base_reading[-1])    # しっぱい → しつぱい
        elif seg[-1] in GEMINATE_ENDS and i + 1 < len(parts) and parts[i + 1][1][:1] in GEMINATE_BEFORE:
            add("geminate", i, seg[:-1] + "っ")
        for k, ch in enumerate(seg):
            if ch in "ゃゅょ":
                add("small", i, seg[:k] + SMALL[ch] + seg[k + 1:])
    seen, result = set(), []
    for fam, r in out:
        if r not in seen:
            seen.add(r)
            result.append((fam, r))
    return result


def pick_varied(variants: list, rng: random.Random, n: int = 3) -> list:
    """n wrong answers from different families when possible (not three long-vowel tricks)."""
    rng.shuffle(variants)
    order = {"other": 0, "long": 1, "voice": 2, "geminate": 3, "small": 4}
    chosen, families = [], set()
    for fam, r in sorted(variants, key=lambda x: order.get(x[0], 9)):
        if fam not in families:
            chosen.append(r)
            families.add(fam)
    for fam, r in variants:
        if len(chosen) >= n:
            break
        if r not in chosen:
            chosen.append(r)
    return chosen[:n]


_homophones = {}


def homophones() -> dict:
    """{reading: [kanji of level N5–N3 or known with that reading]} from data/kanji.json."""
    data = kanji_data()
    if not _homophones and data:
        for k in data:
            if kanji_level_ok(k):
                for r in kanji_readings(k, on_only=True):
                    _homophones.setdefault(r, []).append(k)
    return _homophones


def spelling_variants(word: str, reading: str, rng: random.Random) -> list:
    """Same word written with another kanji of the same reading (利用 → 理用, 利要) — never a real word."""
    parts = split_reading(word, reading)
    if not parts:
        return []
    out = []
    for i, (c, seg) in enumerate(parts):
        if not KANJI.match(c):
            continue
        base_forms = {r for r in kanji_readings(c, on_only=True) if seg in _shapes(r, i == 0, i == len(parts) - 1)}
        others = {k for r in base_forms for k in homophones().get(r, []) if k != c}   # empty for a kun'yomi
        for k in others:
            new = word[:i] + k + word[i + 1:]
            if not lexicon.lookup(new):
                out.append((i, new))
    rng.shuffle(out)
    chosen, positions = [], set()
    for i, w in sorted(out, key=lambda x: x[0] in positions):   # spread over the kanji of the word
        if w not in chosen:
            chosen.append(w)
            positions.add(i)
    return chosen


def valid_readings(word: str) -> set:
    entry = lexicon.lookup(word)
    return {entry["reading"]} if entry and entry["reading"] else set()


# ---------------------------------------------------------------------------
# Question builders — each returns a question dict or None
# ---------------------------------------------------------------------------

def base(id_: int, jp: str, fr: str, qtype: str, level: str, answer: str) -> dict:
    return {"qtype": qtype, "level": level, "full_sentence": jp, "translation": fr or "",
            "show_translation": qtype in NEEDS_LLM or qtype == "ordering", "hint": "", "explanation": "",
            "source": f"Tatoeba #{id_}", "source_url": f"https://tatoeba.org/fr/sentences/show/{id_}",
            "key": f"tatoeba:{id_}:jlpt-{qtype}:{answer}", "v": VERSION}


def with_choices(q: dict, answer: str, distractors: list, rng: random.Random) -> dict:
    choices = [answer] + distractors[:3]
    rng.shuffle(choices)
    q.update(choices=choices, answers=[answer], answer_index=choices.index(answer))
    return q


def q_kanji_reading(id_, jp, fr, tokens, level, rng):
    for k in target_words(tokens, level):
        t = tokens[k]
        valid = valid_readings(t[0]) | {t[3]}
        wrong = pick_varied([v for v in reading_variants(t[3], t[0]) if v[1] not in valid], rng)
        if len(wrong) < 3:
            continue
        q = base(id_, jp, fr, "kanji_reading", level, t[3])
        q["question"] = "".join(x[0] for x in tokens[:k]) + f"【{t[0]}】" + "".join(x[0] for x in tokens[k + 1:])
        q["explanation"] = f"{t[0]} se lit {t[3]}.{meaning_of(t[0])}"
        q["explanation_en"] = f"{t[0]} is read {t[3]}.{meaning_of(t[0])}"
        return with_choices(q, t[3], wrong, rng)
    return None


def q_orthography(id_, jp, fr, tokens, level, rng):
    for k in target_words(tokens, level):
        t = tokens[k]
        wrong = spelling_variants(t[0], t[3], rng)
        if len(wrong) < 3:
            continue
        q = base(id_, jp, fr, "orthography", level, t[0])
        q["question"] = "".join(x[0] for x in tokens[:k]) + f"【{t[3]}】" + "".join(x[0] for x in tokens[k + 1:])
        q["explanation"] = f"{t[3]} s'écrit {t[0]}.{meaning_of(t[0])}"
        q["explanation_en"] = f"{t[3]} is written {t[0]}.{meaning_of(t[0])}"
        return with_choices(q, t[0], wrong, rng)
    return None


_noun_pool = {}


def noun_pool(level: str) -> list:
    key = (level, lexicon._mtime())
    if key not in _noun_pool:
        _noun_pool[key] = [w["word"] for w in lexicon.words(level)
                             if len(w["word"]) <= 4 and all(KANJI.match(c) and kanji_level_ok(c) for c in w["word"])
                             and not w.get("kana")] if lexicon.available() else []
    return _noun_pool[key]


def q_vocab(id_, jp, fr, tokens, level, rng):
    pool = noun_pool(level)
    for k in target_words(tokens, level):
        t = tokens[k]
        if t[1] != "名詞" or len(pool) < 10:
            continue
        context = [x for i, x in enumerate(tokens) if i != k and x[1] in ("名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞")]
        if len(context) < 2:
            continue   # 「（　　）だった。」: nothing in the sentence to decide between the choices
        wrong = [w for w in rng.sample(pool, min(12, len(pool))) if w != t[0] and w not in t[0]][:3]
        if len(wrong) < 3:
            continue
        q = base(id_, jp, fr, "vocab", level, t[0])
        q["question"] = "".join(x[0] for x in tokens[:k]) + "（　　）" + "".join(x[0] for x in tokens[k + 1:])
        q["sentence"] = "".join(x[0] for x in tokens[:k]) + BLANK + "".join(x[0] for x in tokens[k + 1:])
        return with_choices(q, t[0], wrong, rng)
    return None


def next_word(tokens: list, k: int):
    return next((t for t in tokens[k:] if t[1] not in ("空白", "補助記号")), None)


def main_verb_after(tokens: list, k: int):
    return next((t for t in tokens[k:] if t[1] == "動詞" or (t[1] == "名詞" and t[4] in TO_VERBS)), None)


def form_distractors(form: str, answer: str, verb: list, conj_type: str, following) -> list:
    """Other forms of the verb that are NOT also correct here."""
    excluded = {form}
    linking = {"te", "tara", "ba"}
    if form in linking and not (form == "te" and following and following[4] in TE_AUXILIARIES):
        excluded |= linking          # 着て / 着たら / 着れば… can all link two clauses
    others = [conjugate.conjugate(verb[4], f, conj_type) for f in GRAMMAR_FORMS if f not in excluded]
    return [o for o in dict.fromkeys(others) if o and o != answer]


def particle_distractors(tokens: list, k: int, answer: str) -> list:
    wrong = [p for p in CONFUSABLE.get(answer, []) if p != answer]
    verb = main_verb_after(tokens, k + 1)
    lemma = verb[4] if verb else ""
    if lemma in TO_VERBS:
        wrong = [p for p in wrong if {p, answer} != {"に", "と"}]
    if lemma in KARA_VERBS:
        wrong = [p for p in wrong if {p, answer} != {"に", "から"}]
    if answer in ("から", "まで") and lemma in mx.MOVE_VERBS:   # アメリカから / に来ました
        wrong = [p for p in wrong if p not in ("に", "へ", "まで", "から")]
    if answer in ("を", "で") and k > 0 and tokens[k - 1][0].endswith("語"):
        wrong = [p for p in wrong if p not in ("を", "で")]   # 英語を / で話す: the language is both
    if answer in ("を", "が"):   # 水を/が飲みたい, 日本語を/が話せる
        wrong = [p for p in wrong if p not in ("を", "が")]
    return wrong


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
            following = next_word(tokens, b)
            if lexicon.available() and not lexicon.lookup(verb[4]):
                continue   # くびっ|たけ: a word the analyzer cut wrongly
            if not conjugate.verb_class(verb[4], conj_type) or verb[2] == "非自立可能":
                continue   # あり（えない）: the blank would cut a word in two
            if following is None or following[2] == "終助詞" or following[1] == "助動詞":
                continue   # at the end of a sentence, 教えて / 教えよう / 教えます… are all possible
            if following[0] in ("と", "って") and following[1] == "助詞":
                continue   # before a quote (と思う, と言った) every finite form fits
            wrong = form_distractors(form, answer, verb, conj_type, following)
            if len(wrong) < 3:
                continue
            rng.shuffle(wrong)
            q = base(id_, jp, fr, "grammar", level, answer)
            before = "".join(x[0] for x in tokens[:a])
            after = "".join(x[0] for x in tokens[b:])
            q.update(question=before + "（　　）" + after, sentence=before + BLANK + after, form=form)
            return with_choices(q, answer, wrong, rng)
    spots = [k for k, t in enumerate(tokens) if t[0] in PARTICLES and t[1] == "助詞"
             and t[2] in ("格助詞", "係助詞", "副助詞") and mx.simple_particle_context(tokens, k)]
    rng.shuffle(spots)
    for k in spots:
        answer = tokens[k][0]
        wrong = particle_distractors(tokens, k, answer)
        if len(wrong) < 3:
            continue
        rng.shuffle(wrong)
        q = base(id_, jp, fr, "grammar", level, answer)
        before = "".join(x[0] for x in tokens[:k])
        after = "".join(x[0] for x in tokens[k + 1:])
        q.update(question=before + "（　　）" + after, sentence=before + BLANK + after)
        return with_choices(q, answer, wrong, rng)
    return None


def chunk_tokens(tokens: list) -> list:
    """Splits a sentence into pieces (bunsetsu-like): content word(s) + the particles / endings after them."""
    pieces, current = [], []
    for k, t in enumerate(tokens):
        starts = t[1] in ("名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "接続詞", "感動詞", "接頭辞")
        joins = bool(current) and (
            (t[1] == "名詞" and current[-1][1] in ("名詞", "接頭辞")                        # compound nouns
             and not (len(current[-1]) > 5 and current[-1][5] == "副詞可能"))            # but not 毎朝 + 駅
            or (t[1] == "動詞" and t[2] == "非自立可能" and current[-1][0] in ("て", "で"))  # 食べて + いる
            or (t[1] == "動詞" and t[4] in ("する", "為る") and current[-1][1] == "名詞")  # 勉強 + する
            or (t[1] == "動詞" and t[4] in ("する", "為る") and current[-1][0] == "どう")  # どう + して
            or (t[1] == "動詞" and t[2] == "非自立可能" and current[-1][1] == "動詞")    # 急ぎ + なさい
            or (t[0].startswith("そう") and t[1] in ("形状詞", "助動詞") and current[-1][1] in ("形容詞", "動詞"))  # 悲し + そう
            or current[-1][1] == "接頭辞")
        if starts and current and not joins:
            pieces.append(current)
            current = []
        current.append(t)
    if current:
        pieces.append(current)
    return pieces


def chunks(tokens: list) -> list:
    return ["".join(x[0] for x in p) for p in chunk_tokens(tokens)]


CASE_ENDINGS = {"が", "を", "に", "で", "へ", "と", "から", "まで", "より"}
TOPIC_ENDINGS = {"は", "も", "でも", "って", "なら", "ば", "たら", "ても", "では", "には", "たり", "だり", "とか", "や"}
FOCUS_ENDINGS = {"か", "だけ", "しか", "ばかり", "など", "くらい", "ぐらい", "ほど"}   # 何か, 私だけ
DEGREE_ADVERBS = {"とても", "少し", "すこし", "もっと", "一番", "いちばん", "大変", "たいへん", "かなり",
                  "ちょっと", "非常", "本当", "ずいぶん", "随分"}


def movable(piece: list, following: list) -> bool:
    """Pieces that Japanese word order lets move around: arguments with a case particle (塩を, 駅に),
    topics (今日は), adverbs (もう, 毎朝). With two of them, the four pieces have several correct orders."""
    last, first = piece[-1], piece[0]
    if last[0] in CASE_ENDINGS and last[1] in ("助詞", "助動詞"):
        return True   # (the analyzer sometimes tags this で as 助動詞)
    if last[1] == "助詞" and last[2] == "接続助詞" and last[0] not in ("て", "で"):
        return True   # 少なくとも, 暑いので, 行くけど: clauses and adverbs
    if last[0] in ("て", "で") and last[2] == "接続助詞" and not (following and following[0][1] == "動詞"
                                                                  and following[0][2] == "非自立可能"):
        return True   # 恥ずかしくて: a clause that can come before or after the others
    if last[0] == "に" and (first[1] == "形状詞" or last[1] == "助動詞"):
        return True   # まともに, 静かに, そんな風に: adverbs
    if last[1] == "助詞" and last[0] in FOCUS_ENDINGS:
        return True   # 何か, 他に何か…
    if all(t[1] in ("名詞", "代名詞", "接尾辞") for t in piece):
        return True   # a noun without its particle (トム今日, 嘘): spoken style, it can go almost anywhere
    if len(piece) == 1 and first[1] == "形容詞" and first[0].endswith("く") and not (
            following and following[0][4] in ("なる", "成る", "する", "為る")):
        return True   # よく, 早く used as adverbs
    if first[1] in ("副詞", "接続詞") or (len(first) > 5 and first[5] == "副詞可能" and len(piece) == 1):
        # a degree adverb right before an adjective that modifies a noun is not movable (とても高い山);
        # before a verb phrase it is (少しラジオの音を大きくして = ラジオの音を少し大きくして)
        return not (first[0] in DEGREE_ADVERBS and following and following[0][1] in ("形容詞", "形状詞")
                    and following[-1][1] in ("形容詞", "形状詞", "助動詞") and not following[-1][0].endswith("く"))
    return False


def modifier_kinds(window: list, following) -> list:
    """For each piece: "gen" for 〜の, "adj" for what modifies a noun further right (an adjective,
    a relative clause, この / その…), "" otherwise. Computed right to left: in 直してある古い汽車,
    直してある modifies 汽車 too."""
    kinds = [""] * len(window)
    for i in range(len(window) - 1, -1, -1):
        piece = window[i]
        nxt = window[i + 1] if i + 1 < len(window) else following
        last = piece[-1]
        before_noun = bool(nxt) and (nxt[0][1] in ("名詞", "代名詞", "接頭辞") or (i + 1 < len(window) and kinds[i + 1]))
        if last[0] == "の" and last[1] == "助詞":
            # 次の, 今日の, 最寄りの behave like adjectives: they swap with 私の (次のあなたの試合)
            head = piece[-2] if len(piece) > 1 else piece[0]
            kinds[i] = "adj" if len(head) > 5 and head[5] in ("副詞可能", "形状詞可能") else "gen"
        elif piece[0][1] == "連体詞" and len(piece) == 1:
            kinds[i] = "adj"
        elif len(piece) == 1 and piece[0][0] in DEGREE_ADVERBS and i + 1 < len(window) and kinds[i + 1] == "adj":
            kinds[i] = "adv"   # とても + 美味しい + 料理: the adverb belongs to the modifier
        elif before_noun and (last[1] in ("形容詞", "形状詞", "動詞") or (last[1] == "接尾辞" and last[2] == "形容詞的")
                              or (last[1] == "助動詞" and last[0] in ("な", "た", "だ", "ない", "そうな"))):
            kinds[i] = "adj"
    return kinds


def q_ordering(id_, jp, fr, tokens, level, rng):
    if re.search(r"[。！？!?]", jp.rstrip("。！？!?」")) or re.search(r"[「」『』…・]", jp):
        return None   # two sentences in one, dialogues
    pieces = chunk_tokens(tokens)
    if len(pieces) < 5:
        return None
    texts = ["".join(x[0] for x in p) for p in pieces]
    starts = list(range(0, len(pieces) - 4))   # never the last piece (it carries the end of the sentence)
    rng.shuffle(starts)
    for start in starts:
        window = pieces[start:start + 4]
        four = texts[start:start + 4]
        if len(set(four)) < 4 or any(len(p) > 9 or not re.search(r"[぀-鿿]", p) for p in four):
            continue
        if any(re.search(r"[、，：:；;（）()—\-]", p) for p in four):
            continue
        if any(p[-1][0] in TOPIC_ENDINGS for p in window):
            continue   # 彼は / 今日は / 君のためなら: can nearly always move to the front
        moving = sum(movable(p, pieces[start + i + 1] if start + i + 1 < len(pieces) else None)
                     for i, p in enumerate(window))
        if moving > 1:
            continue
        kinds = modifier_kinds(window, pieces[start + 4] if start + 4 < len(pieces) else None)
        if any(a and b and a != "adv" for a, b in zip(kinds, kinds[1:])):
            continue   # 彼女の + 新しい + 帽子, 最寄りの + 地下鉄の + 駅: the two modifiers can swap
        if any(len(p) == 1 or all(t[4] in ("する", "為る") or t[1] == "助動詞" for t in w)
               for p, w in zip(four, window)):
            continue   # one-kana pieces, or せよ / して alone (the end of いずれにせよ…)
        star = four[2]
        order = four[:]
        rng.shuffle(order)
        q = base(id_, jp, fr, "ordering", level, star)
        before = "".join(texts[:start])
        after = "".join(texts[start + 4:])
        q["question"] = f"{before}＿＿ ＿＿ ★ ＿＿{after}"
        q.update(choices=order, answers=[star], answer_index=order.index(star),
                 explanation="Ordre : " + " → ".join(four) + f"\n★ = {star}",
                 explanation_en="Order: " + " → ".join(four) + f"\n★ = {star}")
        return q
    return None


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
        "explanation_en": {"type": "string"},
    },
    "required": ["alternatives", "good_example", "problem", "explanation", "explanation_en"],
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
3. "explanation": in 1 to 3 sentences in French, why « {answer} » is right and the others are not.
4. "explanation_en": the same explanation in English."""
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
    q["explanation_en"] = str(result.get("explanation_en", "")).strip()
    return True, ""


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def candidates(level: str, seed=None) -> list:
    if not BANK_PATH.exists():
        raise mx.GenerationError("Bank not found. Run first: python build_bank.py")
    db = sqlite3.connect(BANK_PATH)
    # both translations: questions go to the shared bank, used in French and in English
    rows = db.execute("SELECT id, jp, fr, en, tokens, word_count FROM sentences "
                      "WHERE word_count BETWEEN 3 AND ? AND fr IS NOT NULL AND en IS NOT NULL",
                      (MAX_WORDS.get(level, 12) + ORDERING_EXTRA_WORDS,)).fetchall()
    db.close()
    rng = random.Random(seed)
    rng.shuffle(rows)
    return rows


def used_sentence_ids(keys) -> set:
    """Sentences already used by a JLPT question (keys « tatoeba:<id>:jlpt-<type>:<answer> »)."""
    out = set()
    for key in keys:
        parts = (key or "").split(":")
        if len(parts) > 2 and parts[0] == "tatoeba" and parts[2].startswith("jlpt-"):
            out.add(parts[1])
    return out


def generate(level: str, qtype: str, count: int, model: str = llm.DEFAULT_MODEL, no_llm: bool = False,
             skip_keys=frozenset(), seed=None, log=print, should_stop=lambda: False, rows=None,
             used_ids: set = None) -> list:
    """used_ids: sentence ids not to use again (one sentence = one question, so that a question never
    gives away the answer of another one); the ids used here are added to it."""
    used_ids = used_sentence_ids(skip_keys) if used_ids is None else used_ids
    if qtype in NEEDS_LLM and no_llm:
        log(f"  {LABELS[qtype]}: skipped (needs the LLM check)")
        return []
    rng = random.Random(seed)
    made, dropped, used = [], 0, set()
    max_words = MAX_WORDS.get(level, 12) + (ORDERING_EXTRA_WORDS if qtype == "ordering" else 0)
    for id_, jp, fr, en, tokens_json, word_count in rows if rows is not None else candidates(level, seed):
        if len(made) >= count or dropped > count * 4 or should_stop():
            break
        if str(id_) in used_ids or word_count > max_words:
            continue
        tokens = json.loads(tokens_json)
        if any(t[1] == "感動詞" and t[2] == "フィラー" for t in tokens):
            continue   # usually a word the analyzer did not recognise (あうつもり → あ + う)
        if not sentence_fits(tokens, level):
            continue
        q = BUILDERS[qtype](id_, jp, fr, tokens, level, rng)
        if q:
            q["translation_en"] = en or ""
            q["words"] = words.segment(tokens)
        if not q or q["key"] in skip_keys or q["answers"][0] in used:
            continue
        if qtype in NEEDS_LLM:
            try:
                ok, reason = check(q, model)
            except llm.OllamaUnavailable:
                raise mx.GenerationError(f"Cannot reach Ollama on {llm.OLLAMA_URL}. Start Ollama, or use --no-llm.")
            if not ok:
                dropped += 1
                log(f"  ✗ {q['question']}  ({reason})")
                continue
        used.add(q["answers"][0])  # vary the tested words
        used_ids.add(str(id_))
        made.append(q)
        log(f"  ✓ {len(made)}/{count}  {q['question']}")
    return made


def fill(db, level: str, per_type: int = 10, types: list = None, model: str = llm.DEFAULT_MODEL,
         no_llm: bool = False, log=print, should_stop=lambda: False) -> int:
    """Tops up each JLPT question type of the level to `per_type` unseen questions. Returns how many were added."""
    unseen = {t["topic"]: t["unseen"] for t in store.topics(db)}
    rows = candidates(level)
    used_ids = used_sentence_ids(store.existing_keys(db))
    added = 0
    for qtype in types or TYPES:
        title = topic_title(level, qtype)
        need = per_type - unseen.get(title, 0)
        if need <= 0 or should_stop():
            continue
        log(f"\n=== {title}: {need} question(s) ===")
        try:
            made = generate(level, qtype, need, model, no_llm, store.existing_keys(db), log=log,
                            should_stop=should_stop, rows=rows, used_ids=used_ids)
        except mx.GenerationError as e:
            log(f"  ! {e}")
            break
        for q in made:
            key = q.pop("key")
            added += store.add_exercise(db, title, "jlpt", q, key)
        hint = ("" if made or qtype in NEEDS_LLM and no_llm else
                " (no new sentence with a single possible order: normal, this type is rare)" if qtype == "ordering" else
                " (no suitable sentence: is data/lexicon.db / data/kanji.json filled?)")
        log(f"  → {len(made)} added{hint}")
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
