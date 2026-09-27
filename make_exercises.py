#!/usr/bin/env python3
"""
Creates a fill-in-the-blank sheet from the bank of real sentences (data/bank.db).

    python make_exercises.py --targets "に,で" --pos 格助詞 --title "Les particules に et で"
    python make_exercises.py --targets "は,が" --pos 助詞 --count 15 --max-words 10
    python make_exercises.py --targets "に,で" --pos 格助詞 --no-llm

Unlike generate_sheet.py, the model invents nothing:
  - sentences come from Tatoeba, the answer is the original word (certain);
  - readings come from the morphological analyzer;
  - the LLM (Ollama) only drops sentences where another answer would also be correct,
    and writes a hint and an explanation. With --no-llm it is not used at all.

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
import urllib.request
import webbrowser
from pathlib import Path

from sheet import BLANK, normalize, save_sheet, split_list

BANK_PATH = Path("data") / "bank.db"
KNOWN_PATH = Path("data") / "known.json"
OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen3:14b"


# ---------------------------------------------------------------------------
# 1. Find candidate sentences in the bank
# ---------------------------------------------------------------------------

def token_matches(token: list, targets: set, pos: str) -> bool:
    surface, category, sub_category = token[0], token[1], token[2]
    if normalize(surface) not in targets:
        return False
    return not pos or pos in (category, sub_category)


BEFORE_PARTICLE = {"名詞", "代名詞", "接尾辞"}   # the particle must follow a noun
STACKED_PARTICLES = {"は", "も"}                 # には, では, にも, でも…
# Nouns that form fixed words with the particle: それで / それに (so, moreover), 何で (why),
# ために (in order to, a separate grammar point)
FIXED_BEFORE = {"それ", "何", "なん", "ため", "為"}
# Verbs that turn に into a compound particle: によって, にとって, について, に対して, に関して…
COMPOUND_VERBS = {"よる", "因る", "依る", "拠る", "とる", "取る", "つく", "就く", "付く", "対する", "関する"}


def simple_context(tokens: list, k: int) -> bool:
    """For a particle, keep only simple « noun + particle » cases.
    Drops すぐに / 親切に (after an adverb or adjective) and には / でも (stacked particles)."""
    if tokens[k][1] != "助詞":
        return True  # this filter only applies to particles
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
# Known vocabulary (from anki_sync.py)
# ---------------------------------------------------------------------------

# Parts of speech checked against the known vocabulary. Particles, auxiliaries, suffixes,
# pronouns, numbers, proper nouns and "light" verbs (いる, ある, する…) always count as known.
CONTENT_POS = {"名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "接続詞"}
ALWAYS_KNOWN_SUB = {"数詞", "固有名詞", "非自立可能"}
KANJI = re.compile(r"[\u3400-\u9fff々]")


def load_known() -> dict:
    if not KNOWN_PATH.exists():
        sys.exit(f"Known vocabulary not found ({KNOWN_PATH}). Open Anki and run: python anki_sync.py")
    data = json.loads(KNOWN_PATH.read_text(encoding="utf-8"))
    words = {normalize(w) for w in data.get("words", [])}
    kanji = set(data.get("kanji", [])) | {c for w in words for c in w if KANJI.match(c)}
    print(f"  known vocabulary: {len(words)} forms, {len(kanji)} kanji (Anki sync of {data.get('date', '?')})")
    return {"words": words, "kanji": kanji}


def unknown_words(tokens: list, skip: int, known: dict) -> list:
    """Content words of the sentence that are not in the known vocabulary (the blank is skipped)."""
    unknown = []
    for k, t in enumerate(tokens):
        if k == skip or t[1] not in CONTENT_POS or t[2] in ALWAYS_KNOWN_SUB:
            continue
        forms = {normalize(t[0]), normalize(t[4]), normalize(t[3])}
        if not forms & known["words"]:
            unknown.append(t[4] or t[0])
    return list(dict.fromkeys(unknown))


def unknown_kanji(sentence: str, known: dict) -> list:
    return sorted({c for c in sentence if KANJI.match(c) and c not in known["kanji"]})


def find_candidates(targets: list, pos: str, min_words: int, max_words: int, french_only: bool,
                    any_context: bool = False, known: dict = None, max_unknown: int = 0,
                    known_kanji_only: bool = False) -> dict:
    """Returns {target: [exercise, …]} for sentences containing exactly ONE of the targets.
    With `known`, sentences with more than `max_unknown` unknown words are skipped."""
    if not BANK_PATH.exists():
        sys.exit(f"Bank not found ({BANK_PATH}). Run first: python build_bank.py")
    target_set = {normalize(t) for t in targets}
    by_target = {normalize(t): [] for t in targets}
    db = sqlite3.connect(BANK_PATH)
    query = "SELECT id, jp, fr, en, tokens FROM sentences WHERE word_count BETWEEN ? AND ?"
    if french_only:
        query += " AND fr IS NOT NULL"
    for id_, jp, fr, en, tokens_json in db.execute(query, (min_words, max_words)):
        tokens = json.loads(tokens_json)
        positions = [k for k, t in enumerate(tokens) if token_matches(t, target_set, pos)]
        if len(positions) != 1:
            continue  # no target, or several (ambiguous blank)
        k = positions[0]
        if not any_context and not simple_context(tokens, k):
            continue
        new_words = []
        if known is not None:
            new_words = unknown_words(tokens, k, known)
            if len(new_words) > max_unknown:
                continue
            if known_kanji_only and unknown_kanji(jp, known):
                continue
        before = "".join(t[0] for t in tokens[:k])
        after = "".join(t[0] for t in tokens[k + 1:])
        reading = "".join(t[3] for t in tokens[:k]) + BLANK + "".join(t[3] for t in tokens[k + 1:])
        by_target[normalize(tokens[k][0])].append({
            "sentence": before + BLANK + after,
            "full_sentence": jp,
            "answers": [tokens[k][0]],
            "reading": reading,
            "translation": fr or en or "",
            "show_translation": True,
            "hint": "",
            "explanation": "",
            "source": f"Tatoeba #{id_}",
            "source_url": f"https://tatoeba.org/fr/sentences/show/{id_}",
            "new_words": new_words,
        })
    db.close()
    return by_target


def balanced_order(by_target: dict, seed) -> list:
    """Alternates the targets (に, で, に, で…) so the sheet is balanced."""
    rng = random.Random(seed)
    pools = [rng.sample(v, len(v)) for v in by_target.values() if v]
    order = []
    while any(pools):
        for pool in pools:
            if pool:
                order.append(pool.pop())
    return order


# ---------------------------------------------------------------------------
# 2. Checking and explanations by the local LLM
# ---------------------------------------------------------------------------

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "alternatives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "correct": {"type": "boolean"},
                },
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
    answer = normalize(ex["answers"][0])
    return {t: ex["sentence"].replace(BLANK, t) for t in targets if normalize(t) != answer}


def build_check_request(ex: dict, targets: list, level: str) -> str:
    answer = ex["answers"][0]
    alternatives = alternative_sentences(ex, targets)
    listed = "\n".join(f"   - « {a} » → {s}" for a, s in alternatives.items()) or "   (none)"
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
   expression or idiom (e.g. お目にかかる, 当てにする, によって), or if the grammar is far above the level.
   "problem": if false, a few words in English saying why; otherwise an empty string.
3. "hint": a short clue in French that helps find « {answer} » without giving it away.
4. "explanation": in 1 to 3 sentences in French, why « {answer} » is the right answer here."""


def call_ollama(model: str, messages: list, no_thinking: bool = True) -> str:
    payload = {"model": model, "messages": messages, "stream": False, "format": CHECK_SCHEMA,
               "options": {"temperature": 0.2}}
    if no_thinking:
        payload["think"] = False  # faster with "thinking" models (qwen3)
    request = urllib.request.Request(OLLAMA_URL, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=300) as r:
            return json.loads(r.read().decode("utf-8"))["message"]["content"]
    except urllib.error.HTTPError as e:
        if e.code == 400 and no_thinking:  # model that does not support the "think" option
            return call_ollama(model, messages, no_thinking=False)
        raise


def check_exercise(ex: dict, targets: list, level: str, model: str) -> tuple:
    """Returns (kept?, reason if dropped)."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_check_request(ex, targets, level)}]
    raw = call_ollama(model, messages)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
    try:
        result = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return False, "unreadable answer"
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
# 3. Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Creates a fill-in-the-blank sheet from real sentences.")
    p.add_argument("--targets", required=True, help="words to find, comma-separated, e.g. « に,で »")
    p.add_argument("--pos", default="",
                   help="required part of speech (SudachiPy), e.g. 格助詞 (case particle), 助詞 (any particle)")
    p.add_argument("--title", default="", help="sheet title")
    p.add_argument("--count", type=int, default=10, help="number of exercises (default: 10)")
    p.add_argument("--min-words", type=int, default=3, help="minimum sentence length, in words")
    p.add_argument("--max-words", type=int, default=12, help="maximum sentence length, in words")
    p.add_argument("--level", default="N5", help="student level, for the explanations")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
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
    p.add_argument("--seed", type=int, default=None, help="to get the same selection of sentences again")
    p.add_argument("--no-open", action="store_true", help="do not open the sheet in the browser")
    args = p.parse_args()

    targets = split_list(args.targets)
    known = load_known() if args.known else None
    by_target = find_candidates(targets, args.pos, args.min_words, args.max_words, not args.english,
                                args.any_context, known, args.max_unknown, args.known_kanji)
    for t, pool in by_target.items():
        print(f"  {t}: {len(pool)} candidate sentence(s)")
    order = balanced_order(by_target, args.seed)
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
                ok, reason = check_exercise(ex, targets, args.level, args.model)
            except urllib.error.URLError:
                sys.exit("Cannot reach Ollama on localhost:11434. Start Ollama, or use --no-llm.")
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
    title = args.title or f"Exercices : {' / '.join(targets)}"
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

    html_path = save_sheet(sheet, "bank-" + "-".join(targets))
    print(f"✓ Sheet created: {html_path}  ({len(kept)} exercises)")
    if not args.no_open:
        webbrowser.open(html_path.resolve().as_uri())


if __name__ == "__main__":
    main()
