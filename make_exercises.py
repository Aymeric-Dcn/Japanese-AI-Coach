#!/usr/bin/env python3
"""
Creates fill-in-the-blank exercises from the bank of real sentences (data/bank.db),
either as an HTML sheet or straight into the app's reserve (--save).

    python make_exercises.py --preset ni-de --known --max-unknown 1 --count 30 --save
    python make_exercises.py --preset te-form --known --save
    python make_exercises.py --targets "に,で" --pos 格助詞 --title "Les particules に et で"
    python make_exercises.py --list-presets

Two kinds of exercises:
  - particles:    the blank is one of --targets (e.g. に / で);
  - conjugations: the blank is a verb in a given form (--form te, past, negative, masu, tai),
                  with its dictionary form shown as a cue: 毎朝パンを___（食べる）から…

The model invents nothing:
  - sentences come from Tatoeba, the answer is the original text (certain);
  - readings come from the morphological analyzer, and the kana spelling is accepted too;
  - the LLM (Ollama) only drops doubtful sentences and writes a hint and an explanation.
    With --no-llm it is not used at all.

Build the bank first: python build_bank.py
"""

import argparse
import datetime
import json
import random
import re
import sqlite3
import sys
import time
import urllib.error
import webbrowser
from pathlib import Path

import curriculum
import conjugate
import llm
from sheet import BLANK, normalize, save_sheet, split_list

BANK_PATH = Path("data") / "bank.db"
KNOWN_PATH = Path("data") / "known.json"

# Ready-made topics = the study programme (curriculum.py). Titles are what the app shows.
PRESETS = curriculum.BY_ID

# Conjugated forms: the verb followed by one of these tokens (surface, allowed parts of speech).
FORMS = {
    "te":       ({"て", "で"}, {"助詞"}),
    "past":     ({"た", "だ"}, {"助動詞"}),
    "negative": ({"ない"}, {"助動詞"}),
    "masu":     ({"ます"}, {"助動詞"}),
    "tai":      ({"たい"}, {"助動詞"}),
    "volitional": ({"う", "よう"}, {"助動詞"}),
    "nagara":   ({"ながら"}, {"助詞"}),
    "ba":       ({"ば"}, {"助詞"}),
    "tara":     ({"たら", "だら"}, {"助動詞"}),
    "causative": ({"せる", "させる"}, {"助動詞"}),
}
FORM_NAMES = {"te": "la forme en て", "past": "le passé en た", "negative": "le négatif en ない",
              "masu": "la forme polie en ます", "tai": "la forme en たい (envie)",
              "volitional": "le volitif en う / よう", "nagara": "la forme en ながら (simultanéité)",
              "ba": "le conditionnel en ば", "tara": "le conditionnel en たら",
              "causative": "le causatif en せる / させる"}


# ---------------------------------------------------------------------------
# 1. Known vocabulary (from anki_sync.py)
# ---------------------------------------------------------------------------

# Parts of speech checked against the known vocabulary. Particles, auxiliaries, suffixes,
# pronouns, numbers, proper nouns and "light" verbs (いる, ある, する…) always count as known.
CONTENT_POS = {"名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "接続詞"}
ALWAYS_KNOWN_SUB = {"数詞", "固有名詞", "非自立可能"}
KANJI = re.compile(r"[㐀-鿿々]")


def load_known() -> dict:
    if not KNOWN_PATH.exists():
        sys.exit(f"Known vocabulary not found ({KNOWN_PATH}). Open Anki and run: python anki_sync.py")
    data = json.loads(KNOWN_PATH.read_text(encoding="utf-8"))
    words = {normalize(w) for w in data.get("words", [])}
    kanji = set(data.get("kanji", [])) | {c for w in words for c in w if KANJI.match(c)}
    print(f"  known vocabulary: {len(words)} forms, {len(kanji)} kanji (Anki sync of {data.get('date', '?')})")
    return {"words": words, "kanji": kanji}


def unknown_words(tokens: list, skip: set, known: dict) -> list:
    """Content words of the sentence that are not in the known vocabulary (the blank is skipped)."""
    unknown = []
    for k, t in enumerate(tokens):
        if k in skip or t[1] not in CONTENT_POS or t[2] in ALWAYS_KNOWN_SUB:
            continue
        forms = {normalize(t[0]), normalize(t[4]), normalize(t[3])}
        if not forms & known["words"]:
            unknown.append(t[4] or t[0])
    return list(dict.fromkeys(unknown))


def unknown_kanji(sentence: str, known: dict) -> list:
    return sorted({c for c in sentence if KANJI.match(c) and c not in known["kanji"]})


# ---------------------------------------------------------------------------
# 2. Finding the blank in a sentence
# ---------------------------------------------------------------------------

BEFORE_PARTICLE = {"名詞", "代名詞", "接尾辞"}   # the particle must follow a noun
STACKED_PARTICLES = {"は", "も"}                 # には, では, にも, でも…
# Nouns that form fixed words with the particle: それで / それに (so, moreover), 何で (why),
# ために (in order to, a separate grammar point)
FIXED_BEFORE = {"それ", "何", "なん", "ため", "為"}
# Verbs that turn に into a compound particle: によって, にとって, について, に対して, に関して…
COMPOUND_VERBS = {"よる", "因る", "依る", "拠る", "とる", "取る", "つく", "就く", "付く", "対する", "関する"}


def pos_matches(token: list, pos: set) -> bool:
    return not pos or token[1] in pos or token[2] in pos


def simple_particle_context(tokens: list, k: int) -> bool:
    """For a particle, keep only simple « noun + particle » cases.
    Drops すぐに / 親切に (after an adverb or adjective) and には / でも (stacked particles)."""
    if tokens[k][2] == "接続助詞":
        return True  # のに / ので… follow a verb or an adjective: nothing to filter here
    previous = next((t for t in reversed(tokens[:k]) if t[1] != "空白"), None)
    following = next((t for t in tokens[k + 1:] if t[1] != "空白"), None)
    if previous is None or previous[1] not in BEFORE_PARTICLE:
        return False
    if previous[0] in FIXED_BEFORE:
        return False
    # 本当に, 静かに, 大切に…: a noun that can act as an adjective + に = adverb, not a particle use.
    # (index 5 exists in banks built after 2026-09-27; older banks simply skip this check)
    if len(previous) > 5 and previous[5] == "形状詞可能" and tokens[k][0] == "に":
        return False
    if following is not None and following[1] == "助詞" and following[0] in STACKED_PARTICLES:
        return False
    if following is not None and following[1] == "動詞" and following[4] in COMPOUND_VERBS:
        return False
    return True


# ---------------------------------------------------------------------------
# Pairs of particles that are often BOTH correct: keep only the sentences where the grammar decides,
# or accept both answers.
# ---------------------------------------------------------------------------

QUESTION_WORDS = {"誰", "だれ", "何", "なに", "なん", "どれ", "どこ", "どちら", "どっち", "いつ", "どの", "どんな",
                  "なぜ", "どうして", "どう", "いくら", "いくつ"}
MOVE_VERBS = {"行く", "いく", "来る", "くる", "帰る", "戻る", "向かう", "出かける", "出掛ける", "引っ越す", "移る",
              "急ぐ", "走る", "飛ぶ", "送る", "逃げる", "進む", "上る", "登る", "下りる", "降りる", "入る", "着く"}
EXIST_VERBS = {"ある", "有る", "在る", "いる", "居る"}
# のに (« although ») and ので (« because ») both fit after any clause: the translation tells which one.
DESPITE = re.compile(r"\b(alors que|pourtant|bien que|malgré|quand même|although|even though|though|despite|in spite)\b", re.I)
BECAUSE = re.compile(r"\b(parce que|puisque|comme je|comme il|comme elle|comme nous|comme on|comme c|étant|because|since|as|so)\b", re.I)
# Before these, に marks a time (以内に, ５時に): へ is never right.
TIME_BEFORE = {"以内", "以前", "以後", "以降", "頃", "ごろ", "間", "うち", "内"}
O_ROW = set("おこごそぞとどのほぼぽもよろ")
ALSO = re.compile(r"\b(aussi|même|également|non plus|ni|also|too|either|even)\b", re.I)


def is_question(tokens: list) -> bool:
    return any(t[0] in ("か", "の", "？", "?") and t[1] in ("助詞", "補助記号") for t in tokens[-3:])


def wa_ga_determined(tokens: list, k: int) -> bool:
    """True when only は or only が is natural at position k. は and が depend on the context (topic,
    contrast, new information), so only clear-cut grammatical cases are kept:
      が  誰が / 何が…; inside a subordinate clause (私が書いた手紙, 雨が降ったので, 彼が来るのを);
          existence after a place (部屋に猫がいる);
      は  a question on another word (これは何ですか, 駅はどこですか)."""
    particle = tokens[k][0]
    before = tokens[k - 1] if k else None
    rest = tokens[k + 1:]
    if particle == "が":
        if before and (before[0] in QUESTION_WORDS or before[4] in QUESTION_WORDS):
            return True
        # the first predicate after が, with its endings
        i = k + 1
        while i < len(tokens) and tokens[i][1] not in ("動詞", "形容詞"):
            if tokens[i][1] == "助詞" and tokens[i][0] in ("は", "が", "も"):
                return False                               # another topic / subject first
            i += 1
        if i >= len(tokens) or tokens[i][1] != "動詞":
            return False                                   # adjective: お兄ちゃんがかわいい人形を… is ambiguous
        j = i + 1
        while j < len(tokens) and tokens[j][1] in ("助動詞", "接尾辞") or (
                j < len(tokens) and tokens[j][1] == "動詞" and tokens[j][2] == "非自立可能"):
            j += 1
        nxt = tokens[j] if j < len(tokens) else None
        after = tokens[j + 1] if j + 1 < len(tokens) else None
        if nxt is None:
            pass
        elif nxt[1] in ("名詞", "代名詞") and nxt[0] not in ("ん",):
            return True                                    # 私が書いた手紙, 彼が来る時
        elif nxt[1] == "助詞" and nxt[2] == "接続助詞" and nxt[0] not in ("て", "で", "が", "けど", "けれど"):
            return True                                    # 雨が降ったので, 彼が来たら
        elif nxt[1] == "助詞" and nxt[2] == "準体助詞" and not (after and after[1] == "助動詞"):
            return True                                    # 彼が来るのを見た (but not 〜のです)
        verb = tokens[i]
        if verb[4] in EXIST_VERBS and any(t[0] == "に" and t[1] == "助詞" for t in tokens[:k]):
            return True                                    # 部屋に猫がいる
        return False
    # は: a question about something else in the sentence (not どの〜も « every »)
    if not is_question(tokens):
        return False
    for i, t in enumerate(rest):
        if t[0] in QUESTION_WORDS or t[4] in QUESTION_WORDS:
            nxt = rest[i + 1] if i + 1 < len(rest) else None
            if not (nxt and nxt[0] in ("も", "でも", "か")):
                return True
    return False


KNOWN_ICHIDAN = {"食べる", "寝る", "出る", "見せる", "教える", "考える", "答える", "覚える", "忘れる", "入れる",
                 "始める", "止める", "やめる", "決める", "着せる", "続ける", "調べる", "比べる", "変える", "伝える"}


E_TO_U = dict(zip("えけげせぜてでねべめれ", "うくぐすずつづぬぶむる"))


def is_potential(lemma: str) -> bool:
    """話せる, 読める, しゃべれる: the potential form of a godan verb (話す, 読む…), not a verb of its own."""
    if len(lemma) < 3 or not lemma.endswith("る") or lemma[-2] not in E_TO_U or lemma in KNOWN_ICHIDAN:
        return False
    if lemma.endswith(("つける", "づける", "かける", "あける", "つづける")):
        return False
    return not _lexicon_has(lemma) and _lexicon_has(lemma[:-2] + E_TO_U[lemma[-2]])


def _lexicon_has(word: str) -> bool:
    try:
        import lexicon
        return bool(lexicon.available() and lexicon.lookup(word))
    except Exception:
        return True


def pair_rule(targets: set, tokens: list, k: int, translation: str):
    """For the particle pairs that overlap: None = drop the sentence, otherwise the extra accepted answers."""
    answer = normalize(tokens[k][0])
    following = next((t for t in tokens[k + 1:] if t[1] == "動詞"), None)
    if targets == {"は", "が"}:
        return [] if wa_ga_determined(tokens, k) else None
    if targets == {"に", "へ"}:
        before = tokens[k - 1] if k else None
        if before and (before[4] in TIME_BEFORE or before[2] in ("数詞", "助数詞")):
            return [] if answer == "に" else None        # １週間以内に: a time, not a direction
        if following and following[4] in MOVE_VERBS:
            return ["へ" if answer == "に" else "に"]      # 日本に / へ行く: both are right
        return None if answer == "へ" else []
    if targets == {"は", "も"}:
        also = bool(ALSO.search(translation or ""))
        return [] if also == (answer == "も") else None   # the translation tells which one
    if targets == {"を", "が"}:
        if following:
            i = tokens.index(following)
            after = tokens[i + 1] if i + 1 < len(tokens) else None
            wants = bool(after) and after[0] == "たい"
            potential = is_potential(following[4])
            between = tokens[k + 1:i]
            direct = not any(t[1] in ("形容詞", "動詞", "助動詞") for t in between)
            person = k > 0 and (tokens[k - 1][2] == "固有名詞" or tokens[k - 1][1] == "代名詞")
            if (wants or potential) and direct and not person:
                return ["が" if answer == "を" else "を"]   # 水を / が飲みたい, 日本語を / が話せる
        return []
    if targets == {"のに", "ので"}:
        despite, because = bool(DESPITE.search(translation or "")), bool(BECAUSE.search(translation or ""))
        answer = normalize(tokens[k][0] + tokens[k + 1][0])
        if answer == "のに":
            return [] if despite and not because else None
        return [] if because and not despite else None   # のに for a purpose (行くのに便利) is dropped too
    if targets == {"と", "や"}:
        nxt = tokens[k + 1] if k + 1 < len(tokens) else None
        before = tokens[k - 1] if k else None
        if answer == "や":
            if not nxt or nxt[1] not in ("名詞", "代名詞") or (before and before[0] in ("今", "いま")):
                return None                               # 今や, poems: not the listing や
            return ["と"]                                 # パンや卵: と is right too
        return []   # « Tom et Marie », 6 と 4: と = the complete list; や (« …entre autres ») would change the meaning
    return []


def particle_blanks(tokens: list, targets: set, pos: set, any_context: bool) -> list:
    """[(start, end)] token spans to blank: exactly one target particle per sentence."""
    if targets == {"のに", "ので"}:
        return noni_node_blanks(tokens)
    spans = [(k, k + 1) for k, t in enumerate(tokens) if normalize(t[0]) in targets and pos_matches(t, pos)]
    if len(spans) != 1:
        return []  # no target, or several (ambiguous blank)
    if not any_context and not simple_particle_context(tokens, spans[0][0]):
        return []
    return spans


def noni_node_blanks(tokens: list) -> list:
    """SudachiPy splits ので into の + で (だ) and のに into の + に: one such pair per sentence."""
    spans = []
    for k in range(len(tokens) - 1):
        no, second = tokens[k], tokens[k + 1]
        if no[0] != "の" or no[2] != "準体助詞":
            continue
        if not ((second[0] == "で" and second[4] == "だ") or (second[0] == "に" and second[2] == "格助詞")):
            continue
        after = tokens[k + 2] if k + 2 < len(tokens) else None
        if after and (after[4] in ("ある", "御座る", "ござる") or after[0] in ("は", "も", "しか", "さえ", "す")):
            continue   # のである, のでは, のには: other constructions
        spans.append((k, k + 2))
    return spans if len(spans) == 1 else []


def volitional_blanks(tokens: list) -> list:
    """SudachiPy keeps the volitional in one token (行こう, 食べよう, しよう)."""
    spans = []
    for k, verb in enumerate(tokens):
        s = verb[0]
        if verb[1] != "動詞" or s == verb[4] or not (s.endswith("よう") or (len(s) > 1 and s[-1] == "う" and s[-2] in O_ROW)):
            continue
        if verb[4].endswith("ずる"):
            continue
        if verb[2] == "非自立可能" and k > 0 and tokens[k - 1][0] in ("て", "で") and tokens[k - 1][2] == "接続助詞":
            continue   # 食べてみよう: the main verb is elsewhere
        spans.append((k, k + 1))
    return spans if len(spans) == 1 else []


def conjugation_blanks(tokens: list, form: str) -> list:
    """[(start, end)] spans « verb + ending » for the form, exactly one per sentence."""
    if form == "volitional":
        return volitional_blanks(tokens)
    endings, ending_pos = FORMS[form]
    spans = []
    for k in range(len(tokens) - 1):
        verb, ending = tokens[k], tokens[k + 1]
        if verb[1] != "動詞" or ending[0] not in endings or ending[1] not in ending_pos:
            continue
        if verb[4].endswith("ずる"):
            continue   # literary verbs (信ずる, 感ずる): the student would expect 信じる
        # Skip auxiliary verbs right after て (食べている, 見てしまう…): the main verb is elsewhere.
        if (verb[2] == "非自立可能" and k > 0 and tokens[k - 1][0] in ("て", "で")
                and tokens[k - 1][2] == "接続助詞"):
            continue
        spans.append((k, k + 2))
    return spans if len(spans) == 1 else []


_analyzer = None


def cue_reading(word: str) -> str:
    """Reading of the verb shown as a cue (手伝う → てつだう), so kanji you don't know can be typed in kana."""
    global _analyzer
    try:
        import build_bank
        if _analyzer is None:
            _analyzer = build_bank.make_analyzer()
        r = build_bank.reading(_analyzer, word)
        return "" if r == word else r
    except (SystemExit, Exception):
        return ""


def build_exercise(id_: int, jp: str, fr: str, en: str, tokens: list, span: tuple, cue: str = "") -> dict:
    a, b = span
    before = "".join(t[0] for t in tokens[:a])
    after = "".join(t[0] for t in tokens[b:])
    answer = "".join(t[0] for t in tokens[a:b])
    kana = "".join(t[3] for t in tokens[a:b])
    reading = "".join(t[3] for t in tokens[:a]) + BLANK + "".join(t[3] for t in tokens[b:])
    return {
        "sentence": before + BLANK + after,
        "full_sentence": jp,
        "answers": list(dict.fromkeys([answer, kana])),   # the kana spelling is accepted too
        "cue": cue,
        "reading": reading,
        "translation": fr or en or "",
        "translation_en": en or "",
        "show_translation": True,
        "hint": "",
        "explanation": "",
        "source": f"Tatoeba #{id_}",
        "source_url": f"https://tatoeba.org/fr/sentences/show/{id_}",
        "new_words": [],
    }


def find_candidates(targets: list = None, form: str = None, pos: str = "", min_words: int = 3,
                    max_words: int = 12, french_only: bool = True, any_context: bool = False,
                    known: dict = None, max_unknown: int = 0, known_kanji_only: bool = False,
                    skip_keys: set = frozenset(), stats: dict = None) -> dict:
    """Returns {group: [exercise, …]}; group = the answer (particles) or the form (conjugations)."""
    if not BANK_PATH.exists():
        sys.exit(f"Bank not found ({BANK_PATH}). Run first: python build_bank.py")
    target_set = {normalize(t) for t in targets or []}
    pos_set = set(split_list(pos))
    groups = {normalize(t): [] for t in targets} if targets else {form: []}
    db = sqlite3.connect(BANK_PATH)
    query = "SELECT id, jp, fr, en, tokens FROM sentences WHERE word_count BETWEEN ? AND ?"
    if french_only:   # both translations: exercises go to the shared bank, used in French and in English
        query += " AND fr IS NOT NULL AND en IS NOT NULL"
    for id_, jp, fr, en, tokens_json in db.execute(query, (min_words, max_words)):
        tokens = json.loads(tokens_json)
        if form:
            spans = conjugation_blanks(tokens, form)
        else:
            spans = particle_blanks(tokens, target_set, pos_set, any_context)
        if not spans:
            continue
        a, b = spans[0]
        answer = "".join(t[0] for t in tokens[a:b])
        key = f"tatoeba:{id_}:{form or 'particle'}:{answer}"
        if key in skip_keys:
            if stats is not None:
                stats["already_saved"] = stats.get("already_saved", 0) + 1
            continue
        extra = []
        if not form:
            extra = pair_rule(target_set, tokens, a, f"{fr or ''} | {en or ''}" if target_set == {"のに", "ので"} else fr or en or "")
            if extra is None:
                continue   # both particles would fit here
        new_words = []
        if known is not None:
            new_words = unknown_words(tokens, set(range(a, b)), known)
            if len(new_words) > max_unknown:
                continue
            if known_kanji_only and unknown_kanji(jp, known):
                continue
        ex = build_exercise(id_, jp, fr, en, tokens, (a, b), cue=tokens[a][4] if form else "")
        if form:
            ex["cue_reading"] = cue_reading(ex["cue"])
            ex["conj_type"] = tokens[a][6] if len(tokens[a]) > 6 else ""
        ex["new_words"] = new_words
        ex["answers"] += [x for x in extra if x not in ex["answers"]]
        ex["key"] = key
        groups[form or normalize(answer)].append(ex)
    db.close()
    return groups


def balanced_order(groups: dict, seed) -> list:
    """Alternates the groups (に, で, に, で…) so the result is balanced."""
    rng = random.Random(seed)
    pools = [rng.sample(v, len(v)) for v in groups.values() if v]
    order = []
    while any(pools):
        for pool in pools:
            if pool:
                order.append(pool.pop())
    return order


# ---------------------------------------------------------------------------
# 3. Checking and explanations by the local LLM
# ---------------------------------------------------------------------------

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "alternatives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"answer": {"type": "string"}, "correct": {"type": "boolean"}},
                "required": ["answer", "correct"],
            },
        },
        "good_example": {"type": "boolean"},
        "problem": {"type": "string"},
        "hint": {"type": "string"},
        "explanation": {"type": "string"},
        "hint_en": {"type": "string"},
        "explanation_en": {"type": "string"},
    },
    "required": ["alternatives", "good_example", "problem", "hint", "explanation", "hint_en", "explanation_en"],
}

SYSTEM_PROMPT = """You are a rigorous Japanese teacher for a French-speaking student.
Hints and explanations are written in FRENCH, clearly and concretely.
You answer only with the requested JSON."""


def alternative_sentences(ex: dict, targets: list) -> dict:
    """{other answer: full sentence with that answer in the blank}, built by the script
    (the model is only asked to judge them, not to write them)."""
    answers = {normalize(a) for a in ex["answers"]}
    return {t: ex["sentence"].replace(BLANK, t) for t in targets if normalize(t) not in answers}


WA_NOTE = " Be precise: は marks the topic, not « the subject »."
# Hints written by rules where the model's hint would give the answer away.
RULE_HINTS = {frozenset({"のに", "ので"}): (
    "Lis la traduction : la première partie est-elle la cause de la seconde, ou la seconde arrive-t-elle malgré elle ?",
    "Read the translation: is the first part the cause of the second, or does the second happen in spite of it?")}
# Set phrases after the volitional, explained by rules.
VOLITIONAL_PHRASES = [
    (("とする", "とし", "とした"), "〜ようとする = essayer de, ou être sur le point de.", "〜ようとする = to try to, or to be about to."),
    (("と思", "かと思"), "〜ようと思う = avoir l'intention de.", "〜ようと思う = to intend to."),
]


def build_particle_request(ex: dict, targets: list, level: str) -> str:
    answer = ex["answers"][0]
    listed = "\n".join(f"   - « {a} » → {s}" for a, s in alternative_sentences(ex, targets).items()) or "   (none)"
    return f"""Here is a real Japanese sentence (Tatoeba corpus) used for a fill-in-the-blank exercise:
{ex["sentence"]}
Original sentence: {ex["full_sentence"]}
Translation: {ex["translation"]}
The expected answer is « {answer} ». Student level: {level}.

1. "alternatives": here are the same sentence with each OTHER possible answer in the blank:
{listed}
   For each one, give "answer" and say in "correct" whether that exact sentence is grammatical,
   natural for a native speaker AND faithful to the translation above.
   Be demanding: an awkward or rare sentence, or one that changes the meaning, is NOT correct.
2. "good_example": true if this sentence is a good exercise on « {answer} » for a {level} student:
   the particle has its normal, basic meaning here. false if « {answer} » is part of a fixed
   expression or idiom (e.g. お目にかかる, 当てにする, 楽しみにする, によって), or if the grammar is far
   above the level.
   "problem": if false, a few words in English saying why; otherwise an empty string.
3. "hint": a short clue in French that helps find « {answer} » without giving it away: point to the role
   of the word before the blank (a time, the place of an action, a destination, the object…).
   Never write the particle itself in the hint.
4. "explanation": in 1 to 3 sentences in French, why « {answer} » is the right answer here, and why each
   other choice is wrong in this sentence.{WA_NOTE if "は" in targets else ""}
5. "hint_en" and "explanation_en": the same hint and explanation, in English."""


def build_conjugation_request(ex: dict, form: str, level: str) -> str:
    answer = ex["answers"][0]
    return f"""Here is a real Japanese sentence (Tatoeba corpus) used for a conjugation exercise:
{ex["sentence"]}   (verb to conjugate: {ex["cue"]})
Original sentence: {ex["full_sentence"]}
Translation: {ex["translation"]}
The student must write « {answer} », {FORM_NAMES[form]} of {ex["cue"]}. Student level: {level}.

1. "alternatives": always an empty list [].
2. "good_example": true if this is a clear, natural example of {FORM_NAMES[form]} for a {level} student.
   false if the sentence is unnatural, archaic, or its grammar is far above the level.
   "problem": if false, a few words in English saying why; otherwise an empty string.
3. "hint": a short clue in French about how to build the form (e.g. the verb group), without giving the answer.
4. "explanation": in 1 or 2 sentences in French, why this form is used here and what it adds to the meaning
   of this sentence. Do NOT explain how the form is built: a rule is written before your text.
5. "hint_en" and "explanation_en": the same hint and explanation, in English."""


QUOTED = re.compile(r"[«「『\"']\s*([ぁ-ん]{1,3})\s*[»」』\"']")


def hint_gives_answer(ex: dict) -> bool:
    """A hint that quotes the answer, or that talks about « French » (the model mixing up languages)."""
    answers = {normalize(a) for a in ex["answers"]}
    for field in ("hint", "hint_en"):
        text = ex.get(field, "")
        if any(normalize(q) in answers for q in QUOTED.findall(text)) or re.search(r"\b(in French|en français)\b", text, re.I):
            return True
    return False


def check_exercise(ex: dict, level: str, model: str, targets: list = None, form: str = None) -> tuple:
    """Returns (kept?, reason if dropped). Fills in the hint and explanation."""
    request = build_conjugation_request(ex, form, level) if form else build_particle_request(ex, targets, level)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": request}]
    try:
        result = llm.ask_json(model, messages, CHECK_SCHEMA)
    except (ValueError, json.JSONDecodeError):
        return False, "unreadable answer"
    if not form:
        alternatives = {normalize(a): s for a, s in alternative_sentences(ex, targets).items()}
        for alt in result.get("alternatives", []) or []:
            if not isinstance(alt, dict):
                continue
            a = normalize(alt.get("answer", ""))
            if a in alternatives and alt.get("correct") is True:
                return False, f"« {alternatives[a]} » judged correct too"
    if result.get("good_example") is False:
        return False, f"not a good example: {str(result.get('problem', '')).strip() or '?'}"
    for field in ("hint", "explanation", "hint_en", "explanation_en"):
        ex[field] = str(result.get(field, "")).strip()
    if not form and hint_gives_answer(ex):
        ex["hint"] = ex["hint_en"] = ""
    if not form and frozenset(normalize(t) for t in targets or []) in RULE_HINTS:
        ex["hint"], ex["hint_en"] = RULE_HINTS[frozenset(normalize(t) for t in targets)]
    if form:   # how the form is built: written by rules, the model only says why it is used
        notes = conjugate.describe(ex["cue"], form, ex["answers"][0], ex.get("conj_type", ""), ex.get("cue_reading", ""))
        if notes and form == "volitional":
            after = ex["sentence"].split(BLANK, 1)[-1]
            for starts, fr, en in VOLITIONAL_PHRASES:
                if after.startswith(starts):
                    notes["rule"], notes["rule_en"] = f'{notes["rule"]} {fr}', f'{notes["rule_en"]} {en}'
                    break
        if notes:
            ex["hint"], ex["hint_en"] = notes["hint"], notes["hint_en"]
            ex["explanation"] = f'{notes["rule"]} {ex["explanation"]}'.strip()
            ex["explanation_en"] = f'{notes["rule_en"]} {ex["explanation_en"]}'.strip()
    return True, ""


class GenerationError(Exception):
    pass


def generate(targets: list, form: str, pos: str, count: int, *, level: str = "N5", model: str = llm.DEFAULT_MODEL,
             no_llm: bool = False, english: bool = False, any_context: bool = False, known: dict = None,
             max_unknown: int = 0, known_kanji: bool = False, min_words: int = 3, max_words: int = 12,
             seed=None, skip_keys=frozenset(), log=print) -> list:
    """Finds, checks and explains up to `count` exercises. Raises GenerationError when nothing can be made."""
    stats = {}
    groups = find_candidates(targets, form, pos, min_words, max_words, not english,
                             any_context, known, max_unknown, known_kanji, set(skip_keys), stats)
    for g, pool in groups.items():
        log(f"  {g}: {len(pool)} candidate sentence(s)")
    order = balanced_order(groups, seed)
    if not order and stats.get("already_saved"):
        raise GenerationError("No new sentence: every match is already in the reserve. Try a larger --max-words, "
                              "or allow more unknown words with --max-unknown.")
    if not order:
        raise GenerationError("No sentence found. Try a larger --max-words, remove --pos, add --english"
                              + (", or allow unknown words with --max-unknown 1." if known else "."))

    kept, dropped = [], 0
    if no_llm:
        kept = order[:count]
    else:
        log(f"→ Checking and explaining with {model}…")
        t0 = time.time()
        for ex in order:
            if len(kept) >= count or dropped >= count * 4:
                break
            try:
                ok, reason = check_exercise(ex, level, model, targets, form)
            except llm.OllamaUnavailable:
                raise GenerationError("Cannot reach Ollama on localhost:11434. Start Ollama, or use --no-llm.")
            except urllib.error.HTTPError as e:
                raise GenerationError(f"Ollama error {e.code}. Is the model installed? Try: ollama pull {model}")
            if ok:
                kept.append(ex)
                log(f"  ✓ {len(kept)}/{count}  {ex['full_sentence']}")
            else:
                dropped += 1
                log(f"  ✗ dropped: {ex['full_sentence']}  ({reason})")
        log(f"  {len(kept)} kept, {dropped} dropped in {time.time() - t0:.0f} s")
    if not kept:
        raise GenerationError("No exercise kept.")
    random.Random(seed).shuffle(kept)  # so the order does not give the alternation away
    return kept


def save_to_reserve(db, title: str, kind: str, targets: list, exercises: list) -> int:
    import store
    added = 0
    for ex in exercises:
        key = ex.pop("key", None)
        ex["allowed_answers"] = targets
        added += store.add_exercise(db, title, kind, ex, key)
    return added


def generate_topic(topic: dict, count: int, db, **options) -> int:
    """Generates exercises for one curriculum topic and adds them to the reserve; returns how many were added."""
    import store
    targets = split_list(topic.get("targets", ""))
    kept = generate(targets, topic.get("form"), topic.get("pos", ""), count, level=topic["level"],
                    skip_keys=store.existing_keys(db), **options)
    return save_to_reserve(db, topic["title"], curriculum.kind(topic), targets, kept)


# ---------------------------------------------------------------------------
# 4. Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Creates fill-in-the-blank exercises from real sentences.")
    p.add_argument("--preset", choices=sorted(PRESETS), help="ready-made topic (see --list-presets)")
    p.add_argument("--list-presets", action="store_true", help="show the ready-made topics and exit")
    p.add_argument("--targets", default="", help="particles to find, comma-separated, e.g. « に,で »")
    p.add_argument("--form", choices=sorted(FORMS), help="conjugation exercise instead of particles")
    p.add_argument("--pos", default="",
                   help="required part(s) of speech (SudachiPy), e.g. 格助詞 (case particle), 助詞 (any particle)")
    p.add_argument("--title", default="", help="topic / sheet title")
    p.add_argument("--count", type=int, default=10, help="number of exercises (default: 10)")
    p.add_argument("--min-words", type=int, default=3, help="minimum sentence length, in words")
    p.add_argument("--max-words", type=int, default=12, help="maximum sentence length, in words")
    p.add_argument("--level", default="N5", help="student level, for the explanations")
    p.add_argument("--model", default=llm.DEFAULT_MODEL, help=f"Ollama model (default: {llm.DEFAULT_MODEL})")
    p.add_argument("--no-llm", action="store_true", help="do not use Ollama (no check, no explanation)")
    p.add_argument("--english", action="store_true", help="accept sentences translated only into English")
    p.add_argument("--any-context", action="store_true",
                   help="particles: also accept すぐに, には, でも… (dropped by default)")
    p.add_argument("--known", action="store_true",
                   help="only sentences built from the words you know in Anki (run anki_sync.py first)")
    p.add_argument("--max-unknown", type=int, default=0,
                   help="with --known: number of unknown words allowed per sentence (default: 0)")
    p.add_argument("--known-kanji", action="store_true",
                   help="with --known: also require every kanji of the sentence to be known")
    p.add_argument("--save", action="store_true", help="add the exercises to the app's reserve instead of a sheet")
    p.add_argument("--seed", type=int, default=None, help="to get the same selection of sentences again")
    p.add_argument("--no-open", action="store_true", help="do not open the sheet in the browser")
    args = p.parse_args()

    if args.list_presets:
        for name, preset in PRESETS.items():
            what = f"form {preset['form']}" if "form" in preset else f"{preset['targets']}  (pos {preset['pos']})"
            print(f"  {name:11} {preset['level']}  {preset['title']:28} {what}")
        return
    if args.preset:
        preset = PRESETS[args.preset]
        args.targets = args.targets or preset.get("targets", "")
        args.form = args.form or preset.get("form")
        args.pos = args.pos or preset.get("pos", "")
        args.title = args.title or preset["title"]
        args.level = preset["level"] if args.level == "N5" else args.level
    targets = split_list(args.targets)
    if bool(targets) == bool(args.form):
        p.error("give either --targets (particles) or --form (conjugation), or a --preset")
    title = args.title or (f"Particules {' / '.join(targets)}" if targets else PRESETS.get(args.form, {}).get(
        "title", f"Forme {args.form}"))

    db = None
    if args.save:
        import store
        db = store.connect()
    known = load_known() if args.known else None
    try:
        kept = generate(targets, args.form, args.pos, args.count, level=args.level, model=args.model,
                        no_llm=args.no_llm, english=args.english, any_context=args.any_context, known=known,
                        max_unknown=args.max_unknown, known_kanji=args.known_kanji, min_words=args.min_words,
                        max_words=args.max_words, seed=args.seed,
                        skip_keys=store.existing_keys(db) if db else frozenset())
    except GenerationError as e:
        sys.exit(str(e))

    if args.save:
        added = save_to_reserve(db, title, "conjugation" if args.form else "particle", targets, kept)
        topic_row = next((t for t in store.topics(db) if t["topic"] == title), {"total": 0, "unseen": 0})
        print(f"✓ {added} exercise(s) added to « {title} » "
              f"({topic_row['unseen']} not seen yet, {topic_row['total']} in total). Start the app: python server.py")
        return

    for ex in kept:
        ex.pop("key", None)
    sheet = {
        "title": title,
        "exercises": kept,
        "meta": {
            "topic": title,
            "level": args.level,
            "model": "Tatoeba" + ("" if args.no_llm else f" · {args.model}"),
            "date": datetime.date.today().isoformat(),
            "allowed_answers": targets,
        },
    }
    html_path = save_sheet(sheet, "bank-" + ("-".join(targets) or args.form))
    print(f"✓ Sheet created: {html_path}  ({len(kept)} exercises)")
    if not args.no_open:
        webbrowser.open(html_path.resolve().as_uri())


if __name__ == "__main__":
    main()
