#!/usr/bin/env python3
"""
Tops up the exercise reserve following the study programme (curriculum.py).

    python fill_reserve.py                 # current topics + the next one, 15 unseen exercises each
    python fill_reserve.py --target 25     # more per topic
    python fill_reserve.py --all           # every topic of the programme
    python fill_reserve.py --topics wa-ga,past
    python fill_reserve.py --no-llm        # instant, without Ollama (no check, no explanation)

Topics where you struggle (under 70 % right over their last answers) get twice as many exercises.
Uses your Anki vocabulary (data/known.json) when it exists: one unknown word allowed per sentence.
The app's « Remplir la réserve » button runs the same thing.
"""

import argparse
import sys
import time
from pathlib import Path

import curriculum
import llm
import make_exercises
import store

WEAK_RATE = 0.7


def plan(db, target: int, ahead: int = 1, all_topics: bool = False, ids: list = None) -> list:
    """[(topic, how many to add, why)] for the topics that need exercises."""
    states = {s["title"]: s for s in store.topic_states(db)}
    chosen, locked_taken = [], 0
    for t in curriculum.TOPICS:
        s = states[t["title"]]
        if ids:
            wanted = t["id"] in ids
        elif all_topics:
            wanted = True
        elif s["state"] == "current":
            wanted = True
        elif s["state"] == "locked" and locked_taken < ahead:
            wanted, locked_taken = True, locked_taken + 1
        elif s["state"] == "passed" and s["rate"] is not None and s["rate"] < WEAK_RATE:
            wanted = True  # passed by hand but still hard: keep some exercises coming
        else:
            wanted = False
        if not wanted:
            continue
        weak = s["rate"] is not None and s["answers"] >= 5 and s["rate"] < WEAK_RATE
        goal = target * 2 if weak else target
        need = goal - s["unseen"]
        if need > 0:
            chosen.append((t, need, "point faible" if weak else s["state"]))
    return chosen


def fill(db, target: int = 15, ahead: int = 1, all_topics: bool = False, ids: list = None,
         model: str = llm.DEFAULT_MODEL, no_llm: bool = False, max_unknown: int = 1,
         log=print, should_stop=lambda: False) -> list:
    """Generates the missing exercises; returns [(topic title, added)]."""
    known = None
    if make_exercises.KNOWN_PATH.exists():
        known = make_exercises.load_known()
    else:
        log("  (no data/known.json: sentences are not filtered by your Anki vocabulary)")
    todo = plan(db, target, ahead, all_topics, ids)
    if not todo:
        log("✓ The reserve is already full for the topics in progress.")
        return []
    log("To do: " + ", ".join(f"{t['title']} +{n}" for t, n, _ in todo))
    results = []
    for topic, need, why in todo:
        if should_stop():
            log("Stopped.")
            break
        log(f"\n=== {topic['title']} ({topic['level']}, {why}): {need} exercise(s) ===")
        try:
            added = make_exercises.generate_topic(topic, need, db, model=model, no_llm=no_llm, known=known,
                                                  max_unknown=max_unknown if known else 0, log=log)
        except make_exercises.GenerationError as e:
            log(f"  ! {e}")
            added = 0
            if "Ollama" in str(e):
                results.append((topic["title"], added))
                break
        results.append((topic["title"], added))
        log(f"  → {added} added")
    total = sum(a for _, a in results)
    log(f"\n✓ {total} exercise(s) added: " + ", ".join(f"{t} +{a}" for t, a in results))
    return results


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Tops up the exercise reserve following the study programme.")
    p.add_argument("--target", type=int, default=15, help="unseen exercises wanted per topic (default: 15)")
    p.add_argument("--ahead", type=int, default=1, help="also prepare the next N locked topics (default: 1)")
    p.add_argument("--all", action="store_true", help="every topic of the programme")
    p.add_argument("--topics", default="", help="only these topic ids, comma-separated (see make_exercises.py --list-presets)")
    p.add_argument("--max-unknown", type=int, default=1, help="unknown Anki words allowed per sentence (default: 1)")
    p.add_argument("--model", default=llm.DEFAULT_MODEL)
    p.add_argument("--no-llm", action="store_true", help="no check, no explanation (instant)")
    args = p.parse_args()

    if not make_exercises.BANK_PATH.exists():
        sys.exit("Bank not found. Run first: python build_bank.py")
    ids = [x.strip() for x in args.topics.split(",") if x.strip()]
    unknown = [i for i in ids if i not in curriculum.BY_ID]
    if unknown:
        sys.exit(f"Unknown topic(s): {', '.join(unknown)}. See: python make_exercises.py --list-presets")
    t0 = time.time()
    fill(store.connect(), args.target, args.ahead, args.all, ids, args.model, args.no_llm, args.max_unknown)
    print(f"({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
