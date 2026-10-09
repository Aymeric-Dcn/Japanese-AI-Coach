#!/usr/bin/env python3
"""
Measures how reliable the LLM check of make_exercises.py is, on a hand-made test set.

    python tools/evaluate.py                          # tests/eval/particle_cases.json with qwen3:14b
    python tools/evaluate.py --model qwen3:8b --runs 3
    python tools/evaluate.py --cases tests/eval/particle_cases.json --verbose

Each case says what the check SHOULD do with a sentence:
  keep         good exercise, a single possible answer
  ambiguous    another answer would also be natural → must be dropped
  not_example  idiom, fixed expression, adverb… → must be dropped

The script prints the score per category, every mistake, and one line to copy into notes/log.md.
Run it again after changing the prompt or the model to see whether things improve.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))   # the project folder (coach/)

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

from coach import llm
from coach.exercises.make_exercises import check_exercise
from coach.exercises.sheet import BLANK

CATEGORIES = ["keep", "ambiguous", "not_example"]


def predict(case: dict, targets: list, level: str, model: str) -> tuple:
    ex = {
        "sentence": case["sentence"],
        "full_sentence": case["sentence"].replace(BLANK, case["answer"]),
        "answers": [case["answer"]],
        "translation": case["translation"],
    }
    ok, reason = check_exercise(ex, level, model, targets=targets)
    if ok:
        return "keep", ""
    if "judged correct too" in reason:
        return "ambiguous", reason
    if reason.startswith("not a good example"):
        return "not_example", reason
    return "error", reason


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Scores the LLM check on a hand-made test set.")
    p.add_argument("--cases", default="tests/eval/particle_cases.json")
    p.add_argument("--model", default=llm.DEFAULT_MODEL)
    p.add_argument("--level", default="N5")
    p.add_argument("--runs", type=int, default=1, help="repeat the whole set N times (the model is not deterministic)")
    p.add_argument("--verbose", action="store_true", help="print every case, not only the mistakes")
    args = p.parse_args()

    data = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases, targets = data["cases"], data["targets"]
    print(f"{len(cases)} cases × {args.runs} run(s) with {args.model}…")

    # score[expected] = [right, total]; "dropped" counts ambiguous and not_example together
    score = {c: [0, 0] for c in CATEGORIES}
    drop_score = [0, 0]
    mistakes = []
    t0 = time.time()
    try:
        for run in range(args.runs):
            for i, case in enumerate(cases, 1):
                got, reason = predict(case, targets, args.level, args.model)
                exp = case["expected"]
                score[exp][1] += 1
                score[exp][0] += got == exp
                if exp != "keep":
                    drop_score[1] += 1
                    drop_score[0] += got in ("ambiguous", "not_example")
                line = f"  {'✓' if got == exp else '✗'} {case['sentence']} ({case['answer']}) expected {exp}, got {got}" \
                       + (f" — {reason}" if reason else "")
                if got != exp:
                    mistakes.append(line)
                if args.verbose or got != exp:
                    print(line, flush=True)
    except llm.OllamaUnavailable as e:
        sys.exit(str(e))

    total_right = sum(s[0] for s in score.values())
    total = sum(s[1] for s in score.values())
    pct = lambda a, b: f"{100 * a / b:.0f} %" if b else "—"
    print(f"\nScore: {total_right}/{total} ({pct(total_right, total)}) in {time.time() - t0:.0f} s")
    for c in CATEGORIES:
        print(f"  {c:12} {score[c][0]}/{score[c][1]} ({pct(*score[c])})")
    print(f"  dropped when it should (ambiguous or not_example, either reason): {pct(*drop_score)}")
    print("\nFor notes/log.md:")
    print(f"- {datetime.date.today().isoformat()} eval {Path(args.cases).name}, {args.model}, {args.runs} run(s): "
          f"{pct(total_right, total)} overall · keep {pct(*score['keep'])} · ambiguous {pct(*score['ambiguous'])} · "
          f"not_example {pct(*score['not_example'])}")


if __name__ == "__main__":
    main()
