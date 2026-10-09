#!/usr/bin/env python3
"""
Quality control of the exercise reserve (data/coach.db).

    python review.py revalidate            # re-checks every exercise with the current rules (also done at startup)
    python review.py export --unseen > batch.json     # a batch to review (by you, or by Claude)
    python review.py reject 123 456 --reason "は and が both possible"
    python review.py import reviewed.json  # applies a reviewed batch: rejections, fixes, new questions

Reviewed batches dropped in data/reviews/ are applied automatically when the app starts
(then renamed *.applied.json).

A rejected exercise leaves the reserve and the review schedule, and its key is remembered so that it is
never generated again. Its past answers stay in the history but no longer count for its topic.

Reviewed batch format (JSON):
    {"reject": [{"id": 123, "reason": "…"}, {"key": "tatoeba:4567:particle:に", "reason": "…"}],
     "update": [{"id": 124, "data": {"explanation": "…", "answers": ["に", "へ"]}}],   # or {"key": …}
     "add":    [{"topic": "JLPT N4 · 文法形式 (grammaire)", "kind": "jlpt", "key": "claude:…", "data": {…}}],
     "approve": [{"id": 125}] or "approve_all": true,     # reviewed: can go to the shared bank
     "reviewer": "Claude"}
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

import curriculum
import store

BANK_PATH = Path("data") / "bank.db"
REVIEWS_DIR = Path("data") / "reviews"


def _tokens(bank, source_key: str):
    parts = (source_key or "").split(":")
    if len(parts) < 3 or parts[0] != "tatoeba" or bank is None:
        return None, None
    row = bank.execute("SELECT tokens, fr, en FROM sentences WHERE id = ?", (parts[1],)).fetchone()
    if not row:
        return None, None
    if parts[2] == "particle" and (parts[3:] or [""])[0] in ("のに", "ので"):
        return json.loads(row[0]), f"{row[1] or ''} | {row[2] or ''}"   # as make_exercises: both translations
    return json.loads(row[0]), row[1] or row[2] or ""


def check_particle(ex: dict, topic: dict, tokens: list, translation: str):
    """None if the exercise no longer passes the rules, else the answers it should accept."""
    import make_exercises as mx
    from sheet import normalize, split_list
    targets = split_list(topic.get("targets", ""))
    spans = mx.particle_blanks(tokens, {normalize(t) for t in targets}, set(split_list(topic.get("pos", ""))), False)
    if not spans:
        return None
    a, b = spans[0]
    if "relative" in split_list(topic.get("pos", "")):
        extra = ["の"]
    else:
        extra = mx.pair_rule({normalize(t) for t in targets}, tokens, a, translation)
    if extra is None:
        return None
    answer = "".join(t[0] for t in tokens[a:b])
    kana = "".join(t[3] for t in tokens[a:b])
    return list(dict.fromkeys([answer, kana] + extra))


def restore_noni_node(db, log=print) -> int:
    """Until 2026-09-29 the check read only the French translation for のに / ので and retired good exercises
    (« both particles possible here »). Forgets those retirements; the next bank pull brings them back."""
    rows = db.execute("SELECT source_key FROM rejected WHERE reason = 'both particles possible here' "
                      "AND (source_key LIKE '%:particle:のに' OR source_key LIKE '%:particle:ので')").fetchall()
    if not rows:
        return 0
    db.execute("DELETE FROM rejected WHERE reason = 'both particles possible here' "
               "AND (source_key LIKE '%:particle:のに' OR source_key LIKE '%:particle:ので')")
    db.commit()
    import bank_sync
    state = bank_sync.load_state()
    state.get("files", {}).pop("exercises/noni-node.jsonl", None)
    bank_sync.save_state(state)
    log(f"Reserve check: {len(rows)} のに / ので exercise(s) retired by mistake will come back with the bank.")
    return len(rows)


def revalidate(db, log=print) -> dict:
    """Re-checks the reserve with the current rules: removes what would no longer be generated
    (ambiguous particles, JLPT questions of an older generator…) and fixes the accepted answers."""
    restore_noni_node(db, log)
    if not BANK_PATH.exists():
        # a server without the Tatoeba bank (Raspberry Pi): it could not re-check the particles anyway, and
        # loading the whole lexicon takes minutes on a small board. The PC does it; the bank passes it on.
        return {"retired": 0, "updated": 0, "translated": 0}
    import jlpt_questions
    import lexicon
    bank = sqlite3.connect(BANK_PATH)
    seen = {r[0] for r in db.execute("SELECT exercise_id FROM schedule")}
    retired, updated = 0, 0
    try:
        for row in db.execute("SELECT id, topic, kind, source_key, data FROM exercises").fetchall():
            ex = json.loads(row["data"])
            reason = None
            if row["kind"] == "particle" and row["topic"] in curriculum.BY_TITLE:
                tokens, translation = _tokens(bank, row["source_key"])
                if tokens is None:
                    continue
                answers = check_particle(ex, curriculum.BY_TITLE[row["topic"]], tokens, translation)
                if answers is None:
                    reason = "both particles possible here"
                elif answers != ex.get("answers"):
                    ex["answers"] = answers
                    db.execute("UPDATE exercises SET data = ? WHERE id = ?", (json.dumps(ex, ensure_ascii=False), row["id"]))
                    updated += 1
            elif row["kind"] == "jlpt":
                word = ex.get("answers", [""])[0]
                if ex.get("qtype") in ("kanji_reading", "orthography", "vocab"):
                    target = word if ex.get("qtype") != "kanji_reading" else ex.get("question", "").split("【")[-1].split("】")[0]
                    if lexicon.available() and lexicon.usually_kana(target):
                        reason = "word usually written in kana"
                if not reason and ex.get("v", 1) < jlpt_questions.VERSION and row["id"] not in seen:
                    reason = "made by an older generator"
            if reason:
                store.retire(db, row["id"], reason)
                retired += 1
        db.commit()
    finally:
        if bank:
            bank.close()
    translated = add_translations(db) + add_cue_readings(db) + add_words(db)
    if retired or updated or translated:
        log(f"Reserve check: {retired} exercise(s) retired, {updated} fixed, {translated} text(s) added (translations, readings, words).")
    return {"retired": retired, "updated": updated, "translated": translated}


KANJI = re.compile(r"[一-鿿々]")


def add_words(db) -> int:
    """Stores the sentence split into words (« words », see words.py) in exercises made before it was
    kept, from the Tatoeba bank: the words of the sentence can then be clicked on any app."""
    import words
    if not BANK_PATH.exists():
        return 0
    bank = sqlite3.connect(BANK_PATH)
    done = 0
    try:
        for row in db.execute("SELECT id, source_key, data FROM exercises").fetchall():
            ex = json.loads(row["data"])
            if words.has_readings(ex.get("words")) or not ex.get("full_sentence"):
                continue
            found = words.from_bank(bank, row["source_key"])
            if not words.matches(found, ex["full_sentence"]):
                continue
            ex["words"] = found
            db.execute("UPDATE exercises SET data = ? WHERE id = ?", (json.dumps(ex, ensure_ascii=False), row["id"]))
            done += 1
        db.commit()
    finally:
        bank.close()
    return done


def add_cue_readings(db) -> int:
    """Stores the reading of the verb to conjugate (手伝う → てつだう) in exercises made before it was
    kept: an app without SudachiPy (phone, Raspberry Pi) can then show it above the verb."""
    try:
        import sudachipy  # noqa: F401  (without it, every reading would come back empty)
    except ImportError:
        return 0
    import tutor
    done = 0
    for row in db.execute("SELECT id, data FROM exercises").fetchall():
        ex = json.loads(row["data"])
        if not ex.get("cue") or ex.get("cue_reading") or not KANJI.search(ex["cue"]):
            continue   # nothing to conjugate, already there, or a verb in kana (する) that needs none
        reading = tutor.reading(ex["cue"])
        if not reading:
            continue
        ex["cue_reading"] = reading
        db.execute("UPDATE exercises SET data = ? WHERE id = ?", (json.dumps(ex, ensure_ascii=False), row["id"]))
        done += 1
    db.commit()
    return done


def add_translations(db) -> int:
    """Stores the French and English translations in exercises made before both were kept
    (an app without the Tatoeba bank, on a phone or a Raspberry Pi, can then show them)."""
    if not BANK_PATH.exists():
        return 0
    bank = sqlite3.connect(BANK_PATH)
    done = 0
    try:
        for row in db.execute("SELECT id, source_key, data FROM exercises").fetchall():
            parts = (row["source_key"] or "").split(":")
            ex = json.loads(row["data"])
            if len(parts) < 2 or parts[0] != "tatoeba" or (ex.get("translation") and ex.get("translation_en")):
                continue
            found = bank.execute("SELECT fr, en FROM sentences WHERE id = ?", (parts[1],)).fetchone()
            if not found:
                continue
            changed = False
            for field, value in (("translation", found[0]), ("translation_en", found[1])):
                if value and not ex.get(field):
                    ex[field] = value
                    changed = True
            if changed:
                db.execute("UPDATE exercises SET data = ? WHERE id = ?", (json.dumps(ex, ensure_ascii=False), row["id"]))
                done += 1
        db.commit()
    finally:
        bank.close()
    return done


def export(db, topic: str = None, unseen: bool = False, limit: int = 500, unreviewed: bool = False) -> list:
    rows = db.execute("""SELECT e.id, e.topic, e.kind, e.source_key, e.data, s.exercise_id IS NOT NULL AS seen
                         FROM exercises e LEFT JOIN schedule s ON s.exercise_id = e.id ORDER BY e.id""").fetchall()
    out = []
    for r in rows:
        if (topic and r["topic"] != topic) or (unseen and r["seen"]):
            continue
        d = json.loads(r["data"])
        if unreviewed and d.get("review"):
            continue
        out.append({"id": r["id"], "topic": r["topic"], "kind": r["kind"], "key": r["source_key"], "seen": bool(r["seen"]),
                    **{k: d.get(k) for k in ("question", "sentence", "full_sentence", "translation", "choices", "answers",
                                             "cue", "tiles", "explanation") if d.get(k) not in (None, "", [])}})
    return out[:limit]


def apply(db, batch: dict, log=print) -> dict:
    counts = {"rejected": 0, "updated": 0, "added": 0}
    for item in batch.get("reject", []):
        reason = item.get("reason", "rejected after review")
        if item.get("key"):
            row = db.execute("SELECT id FROM exercises WHERE source_key = ?", (item["key"],)).fetchone()
            if row:
                counts["rejected"] += store.retire(db, row[0], reason)
            else:   # not in the reserve: just never generate it
                db.execute("INSERT OR IGNORE INTO rejected (source_key, reason, created) VALUES (?, ?, datetime('now'))",
                           (item["key"], reason))
        elif item.get("id"):
            counts["rejected"] += store.retire(db, int(item["id"]), reason)
    for item in batch.get("update", []):
        row = db.execute("SELECT id, data FROM exercises WHERE " + ("source_key = ?" if item.get("key") else "id = ?"),
                         (item.get("key") or int(item["id"]),)).fetchone()
        if row:
            data = json.loads(row["data"])
            data.update(item.get("data", {}))
            db.execute("UPDATE exercises SET data = ? WHERE id = ?", (json.dumps(data, ensure_ascii=False), row["id"]))
            counts["updated"] += 1
    db.commit()
    stamp = {"by": batch.get("reviewer", "review"), "date": batch.get("date") or __import__("datetime").date.today().isoformat()}
    for item in batch.get("add", []):
        data = dict(item["data"], review=stamp)   # written by the reviewer: reviewed
        counts["added"] += store.add_exercise(db, item["topic"], item.get("kind", "jlpt"), data, item.get("key"))
    approve_ids = set()
    for item in batch.get("approve", []):
        row = db.execute("SELECT id FROM exercises WHERE " + ("source_key = ?" if item.get("key") else "id = ?"),
                         (item.get("key") or int(item["id"]),)).fetchone()
        if row:
            approve_ids.add(row[0])
    if batch.get("approve_all"):
        approve_ids |= {r[0] for r in db.execute("SELECT id FROM exercises")}
    counts["approved"] = 0
    for i in approve_ids:
        data = json.loads(db.execute("SELECT data FROM exercises WHERE id = ?", (i,)).fetchone()[0])
        if not data.get("review"):
            data["review"] = stamp
            db.execute("UPDATE exercises SET data = ? WHERE id = ?", (json.dumps(data, ensure_ascii=False), i))
            counts["approved"] += 1
    db.commit()
    log(f"✓ {counts['rejected']} rejected, {counts['updated']} updated, {counts['added']} added, "
        f"{counts['approved']} approved")
    return counts


def apply_pending(db, log=print) -> int:
    """Applies the reviewed batches found in data/reviews/ (then renames them *.applied.json)."""
    done = 0
    for path in sorted(REVIEWS_DIR.glob("*.json")) if REVIEWS_DIR.exists() else []:
        if path.name.endswith(".applied.json"):
            continue
        try:
            counts = apply(db, json.loads(path.read_text(encoding="utf-8")), log=lambda *a: None)
            path.rename(path.with_name(path.stem + ".applied.json"))
            log(f"Reviewed batch {path.name} applied: {counts['rejected']} retired, {counts['updated']} fixed, "
                f"{counts['added']} added, {counts['approved']} approved.")
            done += 1
        except (ValueError, KeyError, OSError) as e:
            log(f"! Reviewed batch {path.name}: {e}")
    return done


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Quality control of the exercise reserve.")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("revalidate", help="re-check the reserve with the current rules")
    e = sub.add_parser("export", help="print a batch of exercises as JSON")
    e.add_argument("--topic", default=None)
    e.add_argument("--unseen", action="store_true", help="only exercises never answered")
    e.add_argument("--limit", type=int, default=500)
    e.add_argument("--unreviewed", action="store_true", help="only exercises not reviewed yet")
    r = sub.add_parser("reject", help="remove exercises by id")
    r.add_argument("ids", nargs="+", type=int)
    r.add_argument("--reason", default="rejected after review")
    i = sub.add_parser("import", help="apply a reviewed batch (reject / update / add)")
    i.add_argument("file")
    p.add_argument("--db", default=None, help="database (default: data/coach.db)")
    args = p.parse_args()
    db = store.connect(args.db)
    if args.command == "revalidate":
        print(revalidate(db))
    elif args.command == "export":
        print(json.dumps(export(db, args.topic, args.unseen, args.limit, args.unreviewed), ensure_ascii=False, indent=1))
    elif args.command == "reject":
        print(f"✓ {sum(store.retire(db, i, args.reason) for i in args.ids)} rejected")
    elif args.command == "import":
        apply(db, json.loads(Path(args.file).read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
