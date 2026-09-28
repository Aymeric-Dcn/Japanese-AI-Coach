"""
Compares local models on the same exercises: which ones they keep, what they explain, how long it takes.
Nothing is added to the reserve; the result is a file to review (data/compare/<date>-<models>.json).

    python compare_models.py --models qwen3:14b,qwen3:30b-a3b
    python compare_models.py --models qwen3:14b,qwen3:30b-a3b --per-topic 3 --jlpt 6

The same candidates (fixed seed) go to every model, so the answers can be put side by side.
"""

import argparse
import copy
import datetime
import json
import random
import sys
import time
from pathlib import Path

import curriculum
import jlpt_questions as jq
import llm
import make_exercises as mx

# A mix of what the reserve needs: particle pairs that overlap, and conjugations.
DEFAULT_TOPICS = ["wa-ga", "ni-e", "wa-mo", "to-ya", "noni-node", "te-form", "ba", "causative", "volitional"]
OUT_DIR = Path("data") / "compare"


def exercise_candidates(topic_ids: list, per_topic: int, seed: int) -> list:
    out = []
    for tid in topic_ids:
        topic = curriculum.BY_ID[tid]
        targets = mx.split_list(topic.get("targets", ""))
        groups = mx.find_candidates(targets, topic.get("form"), topic.get("pos", ""), max_words=12)
        for ex in mx.balanced_order(groups, seed)[:per_topic]:
            out.append({"topic": tid, "level": topic["level"], "targets": targets, "form": topic.get("form"), "ex": ex})
    return out


def jlpt_candidates(level: str, count: int, seed: int) -> list:
    rng = random.Random(seed)
    out, want = [], {"vocab": count // 2, "grammar": count - count // 2}
    for id_, jp, fr, en, tokens_json, word_count in jq.candidates(level, seed):
        if not any(want.values()):
            break
        if word_count > jq.MAX_WORDS.get(level, 12):
            continue
        tokens = json.loads(tokens_json)
        if not jq.sentence_fits(tokens, level):
            continue
        for qtype in [t for t, n in want.items() if n]:
            q = jq.BUILDERS[qtype](id_, jp, fr, tokens, level, rng)
            if q:
                q["translation_en"] = en or ""
                out.append({"topic": f"jlpt-{qtype}", "level": level, "q": q})
                want[qtype] -= 1
                break
    return out


def run(model: str, item: dict) -> dict:
    t0 = time.time()
    try:
        if "q" in item:
            q = copy.deepcopy(item["q"])
            ok, reason = jq.check(q, model)
            result = {k: q.get(k, "") for k in ("explanation", "explanation_en")}
        else:
            ex = copy.deepcopy(item["ex"])
            ok, reason = mx.check_exercise(ex, item["level"], model, item["targets"], item["form"])
            result = {k: ex.get(k, "") for k in ("hint", "hint_en", "explanation", "explanation_en")}
    except (ValueError, json.JSONDecodeError) as e:
        ok, reason, result = False, f"error: {e}", {}
    return {"kept": ok, "reason": reason, "seconds": round(time.time() - t0, 1), **result}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Same exercises, several local models, one file to compare.")
    p.add_argument("--models", default=f"{llm.DEFAULT_MODEL},qwen3:30b-a3b", help="comma-separated Ollama models")
    p.add_argument("--topics", default=",".join(DEFAULT_TOPICS), help="programme topic ids")
    p.add_argument("--per-topic", type=int, default=3)
    p.add_argument("--jlpt", type=int, default=6, help="JLPT vocab + grammar questions (checked by the model)")
    p.add_argument("--level", default="N5")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    items = exercise_candidates([t.strip() for t in args.topics.split(",") if t.strip()], args.per_topic, args.seed)
    items += jlpt_candidates(args.level, args.jlpt, args.seed)
    print(f"{len(items)} items × {len(models)} models")
    results = []
    totals = {m: {"kept": 0, "seconds": 0.0} for m in models}
    for n, item in enumerate(items, 1):
        shown = item["q"]["question"] if "q" in item else item["ex"]["full_sentence"]
        row = {"topic": item["topic"], "key": (item.get("q") or item.get("ex"))["key"], "sentence": shown,
               "answers": (item.get("q") or item.get("ex"))["answers"],
               "choices": item["q"].get("choices") if "q" in item else None,
               "translation": (item.get("q") or item.get("ex")).get("translation", ""), "models": {}}
        for model in models:
            try:
                r = run(model, item)
            except llm.OllamaUnavailable:
                sys.exit("Cannot reach Ollama on localhost:11434. Start Ollama first.")
            row["models"][model] = r
            totals[model]["kept"] += r["kept"]
            totals[model]["seconds"] += r["seconds"]
        marks = "  ".join(f"{m}: {'✓' if row['models'][m]['kept'] else '✗'} {row['models'][m]['seconds']}s" for m in models)
        print(f"{n:>3}. {shown}   {marks}")
        results.append(row)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{datetime.date.today().isoformat()}-{'-vs-'.join(m.replace(':', '_') for m in models)}.json"
    path = OUT_DIR / name
    path.write_text(json.dumps({"models": models, "level": args.level, "seed": args.seed, "totals": totals,
                                "items": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    for m, t in totals.items():
        print(f"{m}: kept {t['kept']}/{len(items)}, {t['seconds'] / max(len(items), 1):.1f} s per item")
    print(f"\n→ {path}  (send this file for review)")


if __name__ == "__main__":
    main()
