#!/usr/bin/env python3
"""
Generates a lesson + fill-in-the-blank exercise sheet with a local LLM (Ollama).
The model writes everything (lesson, vocabulary, sentences, answers); see make_exercises.py
for exercises built from real sentences instead.

Usage:
    python tools/generate_sheet.py --topic "les particules に et で" --level N5 --answers "に,で"
    python tools/generate_sheet.py --topic "la forme en て" --level N5 --count 12 --model gemma3:12b
    python tools/generate_sheet.py --demo          # sample sheet, no Ollama needed

--answers (optional): closed list of possible answers. Exercises whose answer is not in the
list are dropped, and the list is shown on the sheet.

The sheet is saved in sheets/ (HTML + JSON) and opened in the browser.
Standard library only.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))   # the project folder (coach/)

import argparse
import datetime
import json
import re
import sys
import time
import urllib.error
import urllib.request
import webbrowser

from coach.exercises.sheet import BLANK, normalize, save_sheet, split_list

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen3:14b"

# ---------------------------------------------------------------------------
# 1. Output format imposed on the model (structured JSON)
# ---------------------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "lesson": {
            "type": "object",
            "properties": {
                "introduction": {"type": "string"},
                "points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rule": {"type": "string"},
                            "examples": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "jp": {"type": "string"},
                                        "reading": {"type": "string"},
                                        "translation": {"type": "string"},
                                    },
                                    "required": ["jp", "reading", "translation"],
                                },
                            },
                        },
                        "required": ["rule", "examples"],
                    },
                },
            },
            "required": ["introduction", "points"],
        },
        "vocabulary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "reading": {"type": "string"},
                    "meaning": {"type": "string"},
                },
                "required": ["word", "reading", "meaning"],
            },
        },
        "exercises": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sentence": {"type": "string"},
                    "other_answers": {"type": "array", "items": {"type": "string"}},
                    "hint": {"type": "string"},
                    "translation": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["sentence", "other_answers", "hint", "translation", "explanation"],
            },
        },
    },
    "required": ["title", "lesson", "vocabulary", "exercises"],
}

# ---------------------------------------------------------------------------
# 2. The "teacher": system prompt (this is where the LLM is configured)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an experienced Japanese teacher for a French-speaking student.
You are rigorous: every Japanese sentence you write must be natural and grammatically correct.
All explanations, rules, hints, titles and translations are written in FRENCH, clearly and concretely.
You strictly respect the requested level (vocabulary, kanji and grammar).
You answer only with the requested JSON, with no text around it."""


def build_request(topic: str, level: str, count: int, allowed: list) -> str:
    if allowed:
        allowed_rule = (f"- The element in 【 】 MUST be exactly one of: {', '.join(allowed)}.\n"
                        f"  Choose sentences where ONLY ONE of these answers is correct, and use them all "
                        f"about equally.\n")
    else:
        allowed_rule = ""
    return f"""Create a lesson sheet on the topic: « {topic} ».
Student level: {level}.

Expected content:
- "title": a short title in French.
- "lesson": an introduction of 2 to 4 sentences, then 2 to 5 rule points, each with 1 to 3 examples
  ("jp" = the Japanese sentence, "reading" = its reading in hiragana (かな), NEVER in romaji,
  "translation" = the French translation). Each example must illustrate the rule it is listed under.
- "vocabulary": 5 to 10 useful words for this topic ("word" in usual Japanese spelling, "reading" in
  hiragana (NEVER romaji), "meaning" in French).
- "exercises": {count} fill-in-the-blank exercises.

Rules for each exercise:
- "sentence": a COMPLETE and correct Japanese sentence in which you surround with 【 】 the element
  the student must find. Exactly ONE pair of 【 】 per sentence.
- The element in 【 】 is ALWAYS the grammar point of the topic, and nothing else.
  For a topic about particles: only the particle, never the noun or verb next to it.
  For a topic about a conjugation: only the conjugated form.
{allowed_rule}- Every exercise must be about the topic. No exercise about another particle or another rule.
- "other_answers": other acceptable spellings of the same element (e.g. in kanji or in kana),
  otherwise an empty list [].
- "hint": a clue in French that helps without giving the answer.
- "translation": the French translation of the full sentence.
- "explanation": why this is the answer, in 1 to 3 sentences in French, consistent with the answer.
- Vary the sentences and the difficulty, from easiest to hardest.

Format example for ONE exercise (on another topic, the particle を):
{{"sentence": "毎朝パン【を】食べます。", "other_answers": [], "hint": "Qu'est-ce qu'on mange ?",
 "translation": "Je mange du pain tous les matins.",
 "explanation": "を marque le complément d'objet direct : ce qu'on mange."}}"""


# ---------------------------------------------------------------------------
# 3. Calling the local model
# ---------------------------------------------------------------------------

def call_ollama(model: str, messages: list, temperature: float) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": SCHEMA,
        "options": {"temperature": temperature, "num_ctx": 8192},
    }
    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["message"]["content"]


def extract_json(text: str) -> dict:
    # Some models "think out loud" first: drop that part.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON found in the answer")
    return json.loads(text[start : end + 1])


BRACKETS = re.compile(r"[【［\[]([^】］\]]*)[】］\]]")


def clean_exercises(sheet: dict, allowed: list) -> tuple:
    """Turns the 【answers】 into blanks and drops malformed exercises.
    Returns (valid exercises, number dropped)."""
    allowed_norm = {normalize(a) for a in allowed}
    valid, dropped = [], 0
    for ex in sheet.get("exercises", []):
        sentence = str(ex.get("sentence", ""))
        targets = BRACKETS.findall(sentence)
        # Exactly one bracketed element, and no blank already present.
        if len(targets) != 1 or not targets[0].strip() or "_" in sentence or "＿" in sentence:
            dropped += 1
            continue
        target = targets[0].strip()
        # With a closed list, the answer must belong to it (this drops exercises where the
        # model hid the noun instead of the particle, for instance).
        if allowed_norm and normalize(target) not in allowed_norm:
            dropped += 1
            continue
        others = [str(r).strip() for r in ex.get("other_answers", []) or []]
        others = [r for r in others if r and not BRACKETS.search(r)]
        if allowed_norm:
            others = [r for r in others if normalize(r) == normalize(target)]
        valid.append({
            "sentence": BRACKETS.sub(BLANK, sentence, count=1),
            "full_sentence": BRACKETS.sub(lambda m: m.group(1), sentence, count=1),
            "answers": list(dict.fromkeys([target] + others)),
            "hint": str(ex.get("hint", "")),
            "translation": str(ex.get("translation", "")),
            "explanation": str(ex.get("explanation", "")),
        })
    return valid, dropped


def generate(topic: str, level: str, count: int, model: str, temperature: float,
             allowed: list, attempts: int = 3) -> dict:
    # Ask for a few more than needed: some will be dropped.
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_request(topic, level, count + 4, allowed)},
    ]
    base, exercises, seen = None, [], set()
    for attempt in range(1, attempts + 1):
        print(f"→ Generating with {model} (attempt {attempt}/{attempts})…")
        t0 = time.time()
        try:
            raw = call_ollama(model, messages, temperature)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            sys.exit(f"Ollama error ({e.code}): {body}\nIs the model installed? Try: ollama pull {model}")
        except urllib.error.URLError:
            sys.exit("Cannot reach Ollama on localhost:11434.\n"
                     "Check that it is running (Ollama app open, or « ollama serve »).")
        print(f"  answer received in {time.time() - t0:.0f} s")
        try:
            sheet = extract_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"  unreadable answer ({e}), retrying.")
            continue
        if base is None:
            base = sheet  # keep the lesson and vocabulary of the first successful attempt
        valid, dropped = clean_exercises(sheet, allowed)
        for ex in valid:
            if normalize(ex["sentence"]) not in seen:
                seen.add(normalize(ex["sentence"]))
                exercises.append(ex)
        print(f"  {len(valid)} valid exercise(s), {dropped} dropped · total: {len(exercises)}/{count}")
        if len(exercises) >= count:
            break
    if base is None or not exercises:
        sys.exit("The model produced no usable exercise. Try another model or a more precise topic.")
    base["exercises"] = exercises[:count]
    return base


# ---------------------------------------------------------------------------
# 4. Sample sheet (to test without Ollama)
# ---------------------------------------------------------------------------

DEMO = {
    "title": "Les particules は et が",
    "lesson": {
        "introduction": "は (prononcé « wa ») indique le thème de la phrase : ce dont on parle. "
                        "が indique le sujet grammatical, souvent une information nouvelle ou mise en avant. "
                        "Les deux se traduisent rarement mot à mot : c'est une question de point de vue.",
        "points": [
            {"rule": "は marque le thème : « en ce qui concerne X… »",
             "examples": [
                 {"jp": "私は学生です。", "reading": "わたしはがくせいです。", "translation": "Je suis étudiant(e)."},
                 {"jp": "今日は暑いです。", "reading": "きょうはあついです。", "translation": "Aujourd'hui, il fait chaud."}]},
            {"rule": "が signale l'existence de quelque chose de nouveau, avec いる / ある",
             "examples": [
                 {"jp": "公園に犬がいます。", "reading": "こうえんにいぬがいます。", "translation": "Il y a un chien dans le parc."}]},
            {"rule": "Un mot interrogatif sujet prend toujours が, et la réponse aussi",
             "examples": [
                 {"jp": "誰が来ましたか。", "reading": "だれがきましたか。", "translation": "Qui est venu ?"},
                 {"jp": "田中さんが来ました。", "reading": "たなかさんがきました。", "translation": "C'est M. Tanaka qui est venu."}]},
            {"rule": "Avec 好き, 嫌い, 上手, 分かる…, l'objet de la préférence ou de la capacité prend が",
             "examples": [
                 {"jp": "私は猫が好きです。", "reading": "わたしはねこがすきです。", "translation": "J'aime les chats."}]},
        ],
    },
    "vocabulary": [
        {"word": "学生", "reading": "がくせい", "meaning": "étudiant(e)"},
        {"word": "犬", "reading": "いぬ", "meaning": "chien"},
        {"word": "猫", "reading": "ねこ", "meaning": "chat"},
        {"word": "好き", "reading": "すき", "meaning": "aimer, apprécier"},
        {"word": "天気", "reading": "てんき", "meaning": "le temps (météo)"},
        {"word": "上手", "reading": "じょうず", "meaning": "doué, habile"},
    ],
    "exercises": [
        {"sentence": "わたし___がくせいです。", "answers": ["は"],
         "hint": "On présente le thème de la phrase.",
         "translation": "Je suis étudiant(e).",
         "explanation": "は marque le thème : « en ce qui me concerne, je suis étudiant ». C'est la structure de base X は Y です."},
        {"sentence": "だれ___きましたか。", "answers": ["が"],
         "hint": "Le sujet est un mot interrogatif.",
         "translation": "Qui est venu ?",
         "explanation": "Un mot interrogatif (だれ, なに, どれ…) utilisé comme sujet prend toujours が, jamais は."},
        {"sentence": "わたしはねこ___すきです。", "answers": ["が"],
         "hint": "Regarde le mot à la fin de la phrase.",
         "translation": "J'aime les chats.",
         "explanation": "すき marque ce qu'on aime avec が : わたしは (thème) ねこが (ce qu'on aime) すきです."},
        {"sentence": "あそこにいぬ___います。", "answers": ["が"],
         "hint": "On signale la présence de quelque chose de nouveau.",
         "translation": "Il y a un chien là-bas.",
         "explanation": "Pour signaler l'existence de quelque chose avec いる / ある, on utilise が : l'information est nouvelle."},
        {"sentence": "きょう___いいてんきですね。", "answers": ["は"],
         "hint": "On parle d'aujourd'hui comme cadre de la phrase.",
         "translation": "Il fait beau aujourd'hui, n'est-ce pas ?",
         "explanation": "きょう est le thème : « aujourd'hui, (il fait) beau temps ». は pose le cadre de la phrase."},
        {"sentence": "「これはなんですか。」「それ___ペンです。」", "answers": ["は"],
         "hint": "La réponse reprend la structure de la question.",
         "translation": "« Qu'est-ce que c'est ? » « C'est un stylo. »",
         "explanation": "La question porte sur これ avec は ; la réponse garde le même thème : それはペンです."},
        {"sentence": "どれ___あなたのかばんですか。", "answers": ["が"],
         "hint": "Encore un mot interrogatif en position de sujet.",
         "translation": "Lequel est ton sac ?",
         "explanation": "どれ est un mot interrogatif sujet : il prend が, comme だれ ou なに."},
        {"sentence": "たなかさんはにほんご___じょうずです。", "answers": ["が"],
         "hint": "Comme すき, じょうず suit un schéma particulier.",
         "translation": "M. Tanaka est doué en japonais.",
         "explanation": "じょうず marque le domaine de compétence avec が : たなかさんは (thème) にほんごが じょうずです."},
    ],
}


# ---------------------------------------------------------------------------
# 5. Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Japanese output in the Windows console
    except Exception:
        pass

    p = argparse.ArgumentParser(description="Generates a lesson + fill-in-the-blank Japanese sheet with a local LLM.")
    p.add_argument("--topic", help="the point to practice, e.g. « les particules に et で »")
    p.add_argument("--level", default="N5", help="student level (N5, N4… or a free description)")
    p.add_argument("--count", type=int, default=10, help="number of exercises (default: 10)")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    p.add_argument("--temperature", type=float, default=0.7, help="model creativity (0 = strict, 1 = varied)")
    p.add_argument("--answers", default="", help="closed list of possible answers, comma-separated, e.g. « に,で »")
    p.add_argument("--demo", action="store_true", help="generate the sample sheet, without Ollama")
    p.add_argument("--no-open", action="store_true", help="do not open the sheet in the browser")
    args = p.parse_args()

    allowed = split_list(args.answers)

    if args.demo:
        sheet = json.loads(json.dumps(DEMO))
        topic, model = "demo particles wa ga", "demo"
        allowed = allowed or ["は", "が"]
    else:
        if not args.topic:
            p.error("give a topic with --topic, or use --demo")
        sheet = generate(args.topic, args.level, args.count, args.model, args.temperature, allowed)
        topic, model = args.topic, args.model

    sheet["meta"] = {
        "topic": topic,
        "level": args.level,
        "model": model,
        "date": datetime.date.today().isoformat(),
        "allowed_answers": allowed,
    }

    html_path = save_sheet(sheet, topic)
    print(f"✓ Sheet created: {html_path}  ({len(sheet['exercises'])} exercises)")
    if not args.no_open:
        webbrowser.open(html_path.resolve().as_uri())


if __name__ == "__main__":
    main()
