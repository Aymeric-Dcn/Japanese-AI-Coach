#!/usr/bin/env python3
"""
The shared exercise bank: a separate repository of reviewed exercises that every copy of the app
can download, so that the app works without a local LLM, and that grows with what everyone generates.

    python bank_sync.py pull                          # download new exercises of the bank (also done at startup)
    python bank_sync.py contribute                    # send the exercises generated here, for review

Maintainer (the one who reviews, with Claude):
    python bank_sync.py import-inbox --repo ../Japanese-AI-Coach-bank   # contributions → local reserve, to review
    python bank_sync.py publish --repo ../Japanese-AI-Coach-bank        # reviewed exercises → bank files

Bank layout (see the bank repository's README):
    manifest.json                      version, date, one entry per file with its sha256 and count
    exercises/<topic-id>.jsonl         one reviewed exercise per line
    rejected.jsonl                     keys removed after review (apps retire them too)
    inbox/<name>-<date>.jsonl          contributions waiting for review

Only exercise content goes to the bank: never answers, progress, Anki data or words you know.
Settings (data/settings.json): bank_url (raw URL or local folder), bank_token (only for a private
repository), bank_contribute ("github:owner/repo" or a folder), contributor.
"""

import argparse
import datetime
import hashlib
import json
import sys
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

import curriculum
import store

STATE_PATH = Path("data") / "bank_sync.json"
# Kinds of exercise this version of the app can show. The bank may hold newer ones: they are skipped.
SUPPORTED_KINDS = {"particle", "conjugation", "jlpt", "order"}
DEFAULT_URL = "https://raw.githubusercontent.com/Aymeric-Dcn/Japanese-AI-Coach-bank/main"
FORMAT = 1
PERSONAL_FIELDS = {"new_words"}           # depend on the student's Anki: never shared
KEEP_OUT = {"id", "status", "source_key", "topic", "kind", "topic_label"}


# ---------------------------------------------------------------------------
# Topics ↔ file names
# ---------------------------------------------------------------------------

def topic_id(title: str) -> str:
    if title in curriculum.BY_TITLE:
        return curriculum.BY_TITLE[title]["id"]
    import jlpt_questions as jq
    for level in jq.EXAM:
        for qtype in jq.TYPES:
            if jq.topic_title(level, qtype) == title:
                return f"jlpt-{level.lower()}-{qtype.replace('_', '-')}"
    return "other-" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"files": {}, "sent": [], "imported_inbox": [], "last_pull": None, "last_added": 0}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def to_line(row) -> dict:
    """An exercise of the reserve as a bank line (without anything personal)."""
    data = {k: v for k, v in json.loads(row["data"]).items() if k not in PERSONAL_FIELDS | KEEP_OUT}
    data.pop("origin", None)
    return {"key": row["source_key"], "topic": row["topic"], "kind": row["kind"], "data": data}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Reading the bank (URL or folder)
# ---------------------------------------------------------------------------

def fetch(source: str, path: str, token: str = "") -> str:
    if not source.startswith(("http://", "https://")):
        return (Path(source) / path).read_text(encoding="utf-8")
    request = urllib.request.Request(source.rstrip("/") + "/" + path, headers={"User-Agent": "japanese-coach"})
    if token:
        request.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


# Texts an exercise already in the reserve can receive from the bank later (never overwritten).
FILLED_FIELDS = ("translation", "translation_en", "hint_en", "explanation_en")
FILL_VERSION = 1   # raise it to read every bank file again once (after adding a field above)


def pull(db, source: str = DEFAULT_URL, token: str = "", log=print) -> int:
    """Adds the bank's new exercises to the reserve and retires the rejected ones. Progress is untouched."""
    state = load_state()
    try:
        manifest = json.loads(fetch(source, "manifest.json", token))
    except (OSError, urllib.error.URLError, ValueError) as e:
        raise RuntimeError(f"bank not reachable ({source}): {e}")
    added = completed = 0
    reread = state.get("fill_version", 0) < FILL_VERSION   # once: complete what was downloaded before
    for entry in manifest.get("files", []):
        path, digest = entry["path"], entry["sha256"]
        if state["files"].get(path) == digest and not reread:
            continue
        text = fetch(source, path, token)
        if sha256(text) != digest:
            log(f"  ! {path}: checksum mismatch, skipped")
            continue
        skipped = False
        for line in text.splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("kind") not in SUPPORTED_KINDS:
                skipped = True
                continue   # a kind of exercise this version cannot show yet: it comes with the next update
            data = dict(item["data"], origin="bank")
            if store.add_exercise(db, item["topic"], item["kind"], data, item["key"]):
                added += 1
            else:
                completed += store.fill_missing(db, item["key"], data, FILLED_FIELDS)
        if not skipped:   # otherwise read again after an update of the app
            state["files"][path] = digest
    retired = 0
    try:
        rejected = [json.loads(l) for l in fetch(source, "rejected.jsonl", token).splitlines() if l.strip()]
    except (OSError, urllib.error.URLError, ValueError):
        rejected = []
    for item in rejected:
        row = db.execute("SELECT id FROM exercises WHERE source_key = ?", (item["key"],)).fetchone()
        if row:
            retired += store.retire(db, row[0], item.get("reason", "rejected in the shared bank"))
    state["fill_version"] = FILL_VERSION
    state.update(last_pull=datetime.datetime.now().isoformat(timespec="seconds"), last_added=added,
                 bank_version=manifest.get("version"), bank_count=manifest.get("count"))
    save_state(state)
    log(f"Shared bank: {added} new exercise(s), {retired} retired (bank of {manifest.get('count', '?')})."
        + (f" {completed} completed (translation…)." if completed else ""))
    return added


# ---------------------------------------------------------------------------
# Sending what was generated here
# ---------------------------------------------------------------------------

def local_exercises(db, exclude: set = frozenset()) -> list:
    """Exercises generated on this computer (not downloaded from the bank), not sent yet."""
    out = []
    for row in db.execute("SELECT * FROM exercises WHERE source_key IS NOT NULL ORDER BY id"):
        data = json.loads(row["data"])
        if data.get("origin") or row["source_key"] in exclude:
            continue
        out.append(to_line(row))
    return out


def contribute(db, dest: str, token: str = "", name: str = "friend", log=print) -> int:
    """Writes the new local exercises to the bank's inbox: a folder (a clone of the bank) or
    « github:owner/repo » (needs a token allowed to write to that repository)."""
    state = load_state()
    lines = local_exercises(db, set(state["sent"]))
    if not lines:
        log("Nothing new to send.")
        return 0
    text = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"inbox/{''.join(c for c in name if c.isalnum() or c in '-_') or 'friend'}-{stamp}.jsonl"
    if dest.startswith("github:"):
        repo = dest[len("github:"):]
        body = json.dumps({"message": f"Contribution {filename}", "content": b64encode(text.encode()).decode()})
        request = urllib.request.Request(f"https://api.github.com/repos/{repo}/contents/{filename}", data=body.encode(),
                                         method="PUT", headers={"Authorization": f"token {token}",
                                                                "Accept": "application/vnd.github+json",
                                                                "User-Agent": "japanese-coach"})
        with urllib.request.urlopen(request, timeout=30):
            pass
    else:
        path = Path(dest) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    state["sent"] += [x["key"] for x in lines]
    save_state(state)
    log(f"✓ {len(lines)} exercise(s) sent for review ({filename}).")
    return len(lines)


# ---------------------------------------------------------------------------
# Maintainer: inbox → review → publish
# ---------------------------------------------------------------------------

def import_inbox(db, repo: Path, log=print) -> int:
    """Adds the contributions waiting in the bank's inbox to the local reserve, marked « to review »."""
    state = load_state()
    added = 0
    for path in sorted((repo / "inbox").glob("*.jsonl")) if (repo / "inbox").exists() else []:
        if path.name in state["imported_inbox"]:
            continue
        n = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                data = dict(item["data"], origin=f"inbox:{path.name}")
                data.pop("review", None)
                n += store.add_exercise(db, item["topic"], item["kind"], data, item["key"])
        state["imported_inbox"].append(path.name)
        log(f"  {path.name}: {n} new exercise(s) to review")
        added += n
    save_state(state)
    return added


def add_translations(by_file: dict) -> None:
    """Fills the missing French / English translation of each sentence from the Tatoeba bank."""
    bank_path = Path("data") / "bank.db"
    if not bank_path.exists():
        return
    import sqlite3
    bank = sqlite3.connect(bank_path)
    try:
        for items in by_file.values():
            for item in items.values():
                parts = item["key"].split(":")
                data = item["data"]
                if parts[0] != "tatoeba" or (data.get("translation") and data.get("translation_en")):
                    continue
                row = bank.execute("SELECT fr, en FROM sentences WHERE id = ?", (parts[1],)).fetchone()
                if row:
                    if row[0] and not data.get("translation"):
                        data["translation"] = row[0]
                    if row[1] and not data.get("translation_en"):
                        data["translation_en"] = row[1]
    finally:
        bank.close()


def publish(db, repo: Path, log=print) -> dict:
    """Writes every reviewed exercise (data.review set) to the bank files, with the manifest.
    Exercises already in the bank stay, unless they were rejected since."""
    repo = Path(repo)
    rejected = {r[0]: r[1] for r in db.execute("SELECT source_key, reason FROM rejected")}
    by_file = {}
    for path in (repo / "exercises").glob("*.jsonl") if (repo / "exercises").exists() else []:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                by_file.setdefault(path.name, {})[item["key"]] = item
    for row in db.execute("SELECT * FROM exercises WHERE source_key IS NOT NULL"):
        if not json.loads(row["data"]).get("review"):
            continue   # generated or contributed, not reviewed yet
        item = to_line(row)
        slot = by_file.setdefault(topic_id(row["topic"]) + ".jsonl", {})
        old = slot.get(item["key"])
        if old:   # keep what the bank already had (e.g. English explanations added during a review)
            item["data"] = dict(old["data"], **{k: v for k, v in item["data"].items() if v not in ("", None, [])})
        slot[item["key"]] = item
    add_translations(by_file)
    (repo / "exercises").mkdir(parents=True, exist_ok=True)
    files, total = [], 0
    for name in sorted(by_file):
        items = [by_file[name][k] for k in sorted(by_file[name]) if k not in rejected]
        text = "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in items)
        (repo / "exercises" / name).write_text(text, encoding="utf-8")
        topics = sorted({x["topic"] for x in items})
        files.append({"path": f"exercises/{name}", "sha256": sha256(text), "count": len(items),
                      "topic": topics[0] if len(topics) == 1 else topics,
                      "topic_en": curriculum.title(topics[0], "en") if len(topics) == 1 else None})
        total += len(items)
    rejected_text = "".join(json.dumps({"key": k, "reason": v}, ensure_ascii=False) + "\n" for k, v in sorted(rejected.items()))
    (repo / "rejected.jsonl").write_text(rejected_text, encoding="utf-8")
    old = {}
    if (repo / "manifest.json").exists():
        old = json.loads((repo / "manifest.json").read_text(encoding="utf-8"))
    manifest = {"format": FORMAT, "version": int(old.get("version", 0)) + 1,
                "updated": datetime.date.today().isoformat(), "count": total, "rejected": len(rejected), "files": files}
    (repo / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_stats(repo, manifest)
    log(f"✓ Bank v{manifest['version']}: {total} exercises in {len(files)} files, {len(rejected)} rejected keys.")
    return manifest


def write_stats(repo: Path, manifest: dict) -> None:
    """STATS.md: what the bank holds, per topic (regenerated at each publish)."""
    lines = [f"# Bank statistics — v{manifest['version']} ({manifest['updated']})", "",
             f"**{manifest['count']}** reviewed exercises · {manifest['rejected']} rejected keys", "",
             "| File | Topic | Exercises |", "| --- | --- | ---: |"]
    for f in manifest["files"]:
        topic = f.get("topic_en") or (f["topic"] if isinstance(f["topic"], str) else ", ".join(f["topic"]))
        lines.append(f"| `{f['path']}` | {topic} | {f['count']} |")
    (Path(repo) / "STATS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    settings = {}
    try:
        settings = json.loads((Path("data") / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    p = argparse.ArgumentParser(description="The shared exercise bank.")
    sub = p.add_subparsers(dest="command", required=True)
    pl = sub.add_parser("pull", help="download the bank's new exercises")
    pl.add_argument("--source", default=settings.get("bank_url") or DEFAULT_URL, help="bank URL or folder")
    c = sub.add_parser("contribute", help="send the exercises generated here, for review")
    c.add_argument("--dest", default=settings.get("bank_contribute", ""), help="« github:owner/repo » or a folder")
    c.add_argument("--name", default=settings.get("contributor", "friend"))
    for name in ("import-inbox", "publish"):
        x = sub.add_parser(name)
        x.add_argument("--repo", required=True, help="local clone of the bank repository")
    p.add_argument("--db", default=None)
    args = p.parse_args()
    db = store.connect(args.db)
    token = settings.get("bank_token", "")
    if args.command == "pull":
        pull(db, args.source, token)
    elif args.command == "contribute":
        if not args.dest:
            sys.exit("Where to? --dest github:owner/repo (with bank_token in data/settings.json) or a folder.")
        contribute(db, args.dest, token, args.name)
    elif args.command == "import-inbox":
        print(f"✓ {import_inbox(db, Path(args.repo))} exercise(s) to review. Then: python review.py export --unreviewed")
    elif args.command == "publish":
        publish(db, Path(args.repo))


if __name__ == "__main__":
    main()
