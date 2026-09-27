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

import llm
from sheet import BLANK, normalize, save_sheet, split_list

BANK_PATH = Path("data") / "bank.db"
KNOWN_PATH = Path("data") / "known.json"

# Ready-made topics. Titles are what the app shows.
PRESETS = {
    "ni-de":     {"targets": "に,で", "pos": "格助詞", "title": "Particules に / で"},
    "ni-e":      {"targets": "に,へ", "pos": "格助詞", "title": "Particules に / へ"},
    "wa-ga":     {"targets": "は,が", "pos": "係助詞,格助詞", "title": "Particules は / が"},
    "wo-ga":     {"targets": "を,が", "pos": "格助詞", "title": "Particules を / が"},
    "to-ya":     {"targets": "と,や", "pos": "格助詞,副助詞", "title": "Particules と / や"},
    "kara-made": {"targets": "から,まで", "pos": "格助詞,副助詞", "title": "Particules から / まで"},
    "te-form":   {"form": "te", "title": "Forme en て"},
    "past":      {"form": "past", "title": "Passé en た"},
    "negative":  {"form": "negative", "title": "Négatif en ない"},
    "masu":      {"form": "masu", "title": "Forme polie en ます"},
    "tai":       {"form": "tai", "title": "Envie : forme en たい"},
}

# Conjugated forms: the verb followed by one of these tokens (surface, allowed parts of speech).
FORMS = {
    "te":       ({"て", "で"}, {"助詞"}),
    "past":     ({"た", "だ"}, {"助動詞"}),
    "negative": ({"ない"}, {"助動詞"}),
    "masu":     ({"ます"}, {"助動詞"}),
    "tai":      ({"たい"}, {"助動詞"}),
}
FORM_NAMES = {"te": "la forme en て", "past": "le passé en た", "negative": "le négatif en ない",
              "masu": "la forme polie en ます", "tai": "la forme en たい (envie)"}


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


def particle_blanks(tokens: list, targets: set, pos: set, any_context: bool) -> list:
    """[(start, end)] token spans to blank: exactly one target particle per sentence."""
    spans = [(k, k + 1) for k, t in enumerate(tokens) if normalize(t[0]) in targets and pos_matches(t, pos)]
    if len(spans) != 1:
        return []  # no target, or several (ambiguous blank)
    if not any_context and not simple_particle_context(tokens, spans[0][0]):
        return []
    return spans


def conjugation_blanks(tokens: list, form: str) -> list:
    """[(start, end)] spans « verb + ending » for the form, exactly one per sentence."""
    endings, ending_pos = FORMS[form]
    spans = []
    for k in range(len(tokens) - 1):
        verb, ending = tokens[k], tokens[k + 1]
        if verb[1] != "動詞" or ending[0] not in endings or ending[1] not in ending_pos:
            continue
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
                    skip_keys: set = frozenset()) -> dict:
    """Returns {group: [exercise, …]}; group = the answer (particles) or the form (conjugations)."""
    if not BANK_PATH.exists():
        sys.exit(f"Bank not found ({BANK_PATH}). Run first: python build_bank.py")
    target_set = {normalize(t) for t in targets or []}
    pos_set = set(split_list(pos))
    groups = {normalize(t): [] for t in targets} if targets else {form: []}
    db = sqlite3.connect(BANK_PATH)
    query = "SELECT id, jp, fr, en, tokens FROM sentences WHERE word_count BETWEEN ? AND ?"
    if french_only:
        query += " AND fr IS NOT NULL"
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
            continue
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
        ex["new_words"] = new_words
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
    },
    "required": ["alternatives", "good_example", "problem", "hint", "explanation"],
}

SYSTEM_PROMPT = """You are a rigorous Japanese teacher for a French-speaking student.
Hints and explanations are written in FRENCH, clearly and concretely.
You answer only with the requested JSON."""


def alternative_sentences(ex: dict, targets: list) -> dict:
    """{other answer: full sentence with that answer in the blank}, built by the script
    (the model is only asked to judge them, not to write them)."""
    answers = {normalize(a) for a in ex["answers"]}
    return {t: ex["sentence"].replace(BLANK, t) for t in targets if normalize(t) not in answers}


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
3. "hint": a short clue in French that helps find « {answer} » without giving it away.
4. "explanation": in 1 to 3 sentences in French, why « {answer} » is the right answer here."""


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
4. "explanation": in 1 to 3 sentences in French, how « {answer} » is formed from « {ex["cue"]} »
   and why this form is used here."""


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
    ex["hint"] = str(result.get("hint", "")).strip()
    ex["explanation"] = str(result.get("explanation", "")).strip()
    return True, ""


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
            print(f"  {name:10} {preset['title']:28} {what}")
        return
    if args.preset:
        preset = PRESETS[args.preset]
        args.targets = args.targets or preset.get("targets", "")
        args.form = args.form or preset.get("form")
        args.pos = args.pos or preset.get("pos", "")
        args.title = args.title or preset["title"]
    targets = split_list(args.targets)
    if bool(targets) == bool(args.form):
        p.error("give either --targets (particles) or --form (conjugation), or a --preset")
    title = args.title or (f"Particules {' / '.join(targets)}" if targets else PRESETS.get(args.form, {}).get(
        "title", f"Forme {args.form}"))

    skip_keys = set()
    if args.save:
        import store
        db = store.connect()
        skip_keys = store.existing_keys(db)

    known = load_known() if args.known else None
    groups = find_candidates(targets, args.form, args.pos, args.min_words, args.max_words, not args.english,
                             args.any_context, known, args.max_unknown, args.known_kanji, skip_keys)
    for g, pool in groups.items():
        print(f"  {g}: {len(pool)} candidate sentence(s)")
    order = balanced_order(groups, args.seed)
    if not order and skip_keys:
        sys.exit("No new sentence: every match is already in the reserve. Try a larger --max-words, "
                 "or allow more unknown words with --max-unknown.")
    if not order:
        sys.exit("No sentence found. Try a larger --max-words, remove --pos, add --english"
                 + (", or allow unknown words with --max-unknown 1." if known else "."))

    kept, dropped = [], 0
    if args.no_llm:
        kept = order[: args.count]
    else:
        print(f"→ Checking and explaining with {args.model}…")
        t0 = time.time()
        for ex in order:
            if len(kept) >= args.count or dropped >= args.count * 4:
                break
            try:
                ok, reason = check_exercise(ex, args.level, args.model, targets, args.form)
            except llm.OllamaUnavailable:
                sys.exit("Cannot reach Ollama on localhost:11434. Start Ollama, or use --no-llm.")
            except urllib.error.HTTPError as e:
                sys.exit(f"Ollama error {e.code}. Is the model installed? Try: ollama pull {args.model}")
            if ok:
                kept.append(ex)
                print(f"  ✓ {len(kept)}/{args.count}  {ex['full_sentence']}")
            else:
                dropped += 1
                print(f"  ✗ dropped: {ex['full_sentence']}  ({reason})")
        print(f"  {len(kept)} kept, {dropped} dropped in {time.time() - t0:.0f} s")
    if not kept:
        sys.exit("No exercise kept.")

    random.Random(args.seed).shuffle(kept)  # so the order does not give the alternation away

    if args.save:
        kind = "conjugation" if args.form else "particle"
        added = 0
        for ex in kept:
            key = ex.pop("key")
            ex["allowed_answers"] = targets
            added += store.add_exercise(db, title, kind, ex, key)
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
