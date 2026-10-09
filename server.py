#!/usr/bin/env python3
"""
The local app: serves the web interface and its API on http://localhost:8000.

    python server.py            # then open http://localhost:8000
    python server.py --open     # opens the browser too
    python server.py --port 8080 --model qwen3:14b

Standard library only (http.server + sqlite3). Everything stays on this computer:
progress in data/coach.db, the LLM through Ollama on localhost.

API (JSON):
    GET  /api/status                   Ollama reachable? bank / reserve / Anki sync present?
    GET  /api/session?new=10                     programme session: reviews due + new ones from current topics
    GET  /api/session?mode=practice&topics=a|b   free practice on chosen topics
    GET  /api/topics                   programme topics with their state (passed / current / locked)
    POST /api/topic_known              {title, known} « Je maîtrise déjà »
    POST /api/fill  |  GET /api/fill   top up the reserve in the background / follow its progress
    POST /api/complete                 words / readings / translations sent by bank_sync.py send-texts
    GET  /api/word?w=食べる             word card: Jisho (cached) + kanji + your deck
    GET|POST /api/settings             automatic Anki sync / reserve filling at startup
At startup (unless --no-maintenance): Anki sync once a day, then the reserve is topped up when Ollama answers.
    POST /api/answer                   {id, correct, answer} → next review date
    GET  /api/stats                    progress numbers
    GET  /api/chat/history?conversation=…
    POST /api/chat                     {conversation, message, exercise?} → streamed NDJSON {"delta": …}
"""

import argparse
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import curriculum
import fill_reserve
import llm
import store
import tutor
import updater

WEB_DIR = Path(__file__).resolve().parent / "web"
PACKAGED = bool(getattr(sys, "frozen", False))   # the .exe built by build_exe.py
if PACKAGED:
    WEB_DIR = Path(getattr(sys, "_MEIPASS", ".")) / "web"
SERVER = {"httpd": None}
for _type, _ext in (("application/manifest+json", ".webmanifest"), ("text/javascript", ".js"), ("text/css", ".css"),
                    ("image/png", ".png")):   # Windows can map these wrongly in its registry
    mimetypes.add_type(_type, _ext)
MODEL = llm.DEFAULT_MODEL
DB_PATH = None  # None = store.DB_PATH (data/coach.db)


class Handler(BaseHTTPRequestHandler):
    server_version = "JapaneseCoach/1.0"

    # ------------------------------------------------------------------ helpers

    def log_message(self, fmt, *args):  # quieter console: only errors
        if len(args) < 2 or str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    def send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def send_file(self, path: Path) -> None:
        if not path.is_file():
            return self.send_json({"error": "not found"}, 404)
        body = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/manifest+json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------ routes

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            if url.path in ("/", "/index.html"):
                page = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace('<html lang="fr">', f'<html lang="{lang()}">', 1)
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(body)
            if url.path.startswith("/static/"):
                name = url.path[len("/static/"):]
                if "/" in name or name.startswith("."):
                    return self.send_json({"error": "not found"}, 404)
                return self.send_file(WEB_DIR / name)
            if url.path == "/api/status":
                return self.send_json(status())
            if url.path == "/api/word":   # the word card (click on a word of a sentence)
                import dictionary
                return self.send_json(dictionary.lookup(query.get("w", "")))
            if url.path == "/api/fill":
                return self.send_json(fill_status())
            if url.path == "/api/settings":
                return self.send_json(public_settings())
            if url.path == "/api/bank":
                return self.send_json(bank_status())
            if url.path == "/api/update":
                return self.send_json(update_status())
            db = store.connect(DB_PATH)
            try:
                if url.path == "/api/session":
                    new = int(query.get("new", 10))
                    if query.get("mode") == "practice":
                        topics = [t for t in query.get("topics", "").split("|") if t]
                        data = {"items": localize(store.session(db, new_limit=new, topics=topics or None))}
                    else:
                        data = store.daily_session(db, new_limit=new, skip_empty=no_local_model())
                        localize(data["items"])
                    for ex in data["items"]:  # exercises saved without the verb's reading (needs SudachiPy here)
                        if ex.get("cue") and not ex.get("cue_reading"):
                            ex["cue_reading"] = tutor.reading(ex["cue"])
                    data["stats"] = store.stats(db)
                    return self.send_json(data)
                if url.path == "/api/jlpt/overview":
                    return self.send_json(jlpt_overview(db, query.get("level") or load_settings()["jlpt_level"]))
                if url.path in ("/api/jlpt/practice", "/api/jlpt/exam"):
                    import jlpt_questions as jq
                    level = query.get("level", "N4")
                    if url.path.endswith("exam"):
                        items = []
                        for qtype, n in jq.EXAM.get(level, {}).items():
                            if n:
                                items += store.pick(db, [jq.topic_title(level, qtype)], n)
                        return self.send_json({"items": localize(items), "minutes": len(items), "plan": jq.EXAM.get(level, {})})
                    types = [t for t in query.get("types", "").split("|") if t in jq.TYPES] or jq.TYPES
                    topics = [jq.topic_title(level, t) for t in types]
                    items = store.pick(db, topics, int(query.get("count", 10)))
                    return self.send_json({"items": localize(items), "stats": store.stats(db)})
                if url.path == "/api/reviews":
                    return self.send_json({"items": localize(store.review_list(
                        db, query.get("topic") or None, query.get("q", ""), query.get("unseen") == "1"))})
                if url.path == "/api/topics":
                    return self.send_json({"topics": topic_states(db)})
                if url.path == "/api/stats":
                    return self.send_json(store.stats(db))
                if url.path == "/api/chat/history":
                    return self.send_json({"messages": store.conversation(db, query.get("conversation", "main"), 200)})
            finally:
                db.close()
            self.send_json({"error": "not found"}, 404)
        except Exception as e:  # keep the app alive, show the error in the page
            self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        try:
            data = self.read_json()
            if url.path == "/api/complete":   # texts computed on another computer (bank_sync.py send-texts)
                import bank_sync
                db = store.connect(DB_PATH)
                try:
                    done = sum(store.fill_missing(db, item.get("key", ""), item.get("data") or {}, bank_sync.FILLED_FIELDS)
                               for item in (data.get("items") or [])[:500])
                finally:
                    db.close()
                return self.send_json({"completed": done})
            if url.path == "/api/answer":
                db = store.connect(DB_PATH)
                try:
                    if data.get("replace"):   # « En fait je ne maîtrise pas »: the answer becomes wrong
                        store.undo_answer(db, int(data["id"]))
                    result = store.record_answer(db, int(data["id"]), bool(data.get("correct")),
                                                 str(data.get("answer", ""))[:100])
                    return self.send_json({"schedule": result, "stats": store.stats(db)})
                finally:
                    db.close()
            if url.path == "/api/answer/undo":
                db = store.connect(DB_PATH)
                try:
                    undone = store.undo_answer(db, int(data["id"]))
                    return self.send_json({"undone": undone, "stats": store.stats(db)})
                finally:
                    db.close()
            if url.path == "/api/reviews/action":
                db = store.connect(DB_PATH)
                try:
                    n = store.review_action(db, list(data.get("ids", [])), str(data.get("action", "")))
                    return self.send_json({"done": n, "stats": store.stats(db)})
                finally:
                    db.close()
            if url.path == "/api/chat":
                return self.chat(data)
            if url.path == "/api/topic_known":
                db = store.connect(DB_PATH)
                try:
                    store.set_topic_known(db, str(data["title"]), bool(data.get("known")))
                    return self.send_json({"topics": topic_states(db)})
                finally:
                    db.close()
            if url.path == "/api/fill":
                return self.send_json(start_fill(data))
            if url.path == "/api/settings":
                save_settings(data)
                return self.send_json(public_settings())
            if url.path == "/api/setup":
                return self.send_json(apply_setup(data))
            if url.path == "/api/ping":        # the page is open (see watch_window)
                WINDOW["ping"], WINDOW["closing"] = time.time(), None
                return self.send_json({"ok": True})
            if url.path == "/api/closing":     # the page is being closed or reloaded
                WINDOW["closing"] = time.time()
                return self.send_json({"ok": True})
            if url.path == "/api/quit":
                self.send_json({"ok": True})
                threading.Timer(0.3, shutdown).start()
                return None
            if url.path == "/api/update/check":
                threading.Thread(target=updater.check, daemon=True).start()
                return self.send_json(update_status())
            if url.path == "/api/update/install":
                if not (PACKAGED and os.name == "nt"):
                    return self.send_json({"error": tr("La mise à jour automatique ne marche que dans l'app Windows.",
                                                       "Automatic updates only work in the Windows app.")}, 400)
                threading.Thread(target=install_update, daemon=True).start()
                return self.send_json(update_status())
            if url.path == "/api/bank/sync":
                return self.send_json(start_bank_job("pull"))
            if url.path == "/api/bank/contribute":
                return self.send_json(start_bank_job("contribute"))
            if url.path == "/api/jlpt/exam_result":
                db = store.connect(DB_PATH)
                try:
                    result = store.save_exam(db, str(data.get("level", "")), data.get("answers", []),
                                             int(data.get("seconds", 0)))
                    return self.send_json(result)
                finally:
                    db.close()
            if url.path == "/api/jlpt/fill":
                return self.send_json(start_jlpt_fill(data))
            if url.path == "/api/fill/stop":
                FILL["stop"] = True
                return self.send_json(fill_status())
            self.send_json({"error": "not found"}, 404)
        except KeyError as e:
            self.send_json({"error": f"missing or unknown: {e}"}, 400)
        except Exception as e:
            self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    def chat(self, data: dict) -> None:
        """Streams the tutor's answer as NDJSON lines: {"delta": "…"} … {"done": true}."""
        conversation = str(data.get("conversation") or "main")[:64]
        message = str(data.get("message") or "").strip()
        if not message:
            return self.send_json({"error": "empty message"}, 400)
        db = store.connect(DB_PATH)
        mode = str(data.get("mode") or "prof")
        messages, labels = tutor.build_messages(db, conversation, message, data.get("exercise"), mode,
                                                str(data.get("scenario") or "free"), lang())

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()  # no Content-Length: the connection closes at the end (HTTP/1.0)

        def emit(obj):
            self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()

        answer = []
        try:
            if labels:
                emit({"refs": labels})
            for piece in llm.chat_stream(chat_model(), messages):
                answer.append(piece)
                emit({"delta": piece})
            store.add_message(db, conversation, "user", message)
            store.add_message(db, conversation, "assistant", "".join(answer))
            emit({"done": True})
        except llm.OllamaUnavailable:
            emit({"error": "Ollama ne répond pas. Lance l'application Ollama, puis réessaie."})
        except llm.CloudError as e:
            emit({"error": str(e)})
        except urllib.error.HTTPError as e:
            emit({"error": f"Erreur Ollama {e.code}. Le modèle {MODEL} est-il installé ? (ollama pull {MODEL})"})
        except (BrokenPipeError, ConnectionResetError):
            pass  # the page was closed
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Filling the reserve in the background (« Remplir la réserve »)
# ---------------------------------------------------------------------------

FILL = {"running": False, "stop": False, "log": [], "started": None, "finished": None, "added": None, "title": ""}
FILL_LOCK = threading.Lock()
SETTINGS_PATH = Path("data") / "settings.json"
DEFAULT_SETTINGS = {"auto_sync": True, "auto_fill": True, "fill_target": 15, "jlpt_level": "N4", "jlpt_auto_fill": True,
                    "language": "fr", "bank_auto_sync": True, "bank_url": "", "bank_token": "",
                    "bank_contribute": "", "contributor": "", "setup_done": None, "local_model": None,
                    "chat_model": "", "api_keys": {}, "updates": "notify", "ollama_url": ""}
LANGUAGES = ("fr", "en")


def lang() -> str:
    """Interface language: « fr » or « en » (data/settings.json)."""
    value = load_settings().get("language", "fr")
    return value if value in LANGUAGES else "fr"


def tr(fr: str, en: str) -> str:
    return en if lang() == "en" else fr


_bank = {"db": None}


def bank_translation(source_key: str, language: str) -> str:
    """The sentence's translation from the Tatoeba bank (for exercises saved before they stored both)."""
    parts = (source_key or "").split(":")
    if len(parts) < 2 or parts[0] != "tatoeba" or not (Path("data") / "bank.db").exists():
        return ""
    if _bank["db"] is None:
        import sqlite3
        _bank["db"] = sqlite3.connect(Path("data") / "bank.db", check_same_thread=False)
    row = _bank["db"].execute(f"SELECT {'en' if language == 'en' else 'fr'} FROM sentences WHERE id = ?",
                              (parts[1],)).fetchone()
    return (row[0] or "") if row else ""


RULE_EXPLANATION_EN = [(" se lit ", " is read "), (" s'écrit ", " is written ")]


def no_local_model() -> bool:
    return load_settings().get("local_model") is False


def topic_states(db) -> list:
    language = lang()
    states = store.topic_states(db, no_local_model())
    for t in states:
        t["label"] = curriculum.title(t["title"], language)
    return states


def answer_reading(ex: dict) -> str:
    """Kana of a JLPT question's answer: from the words of the full sentence (or the 【kana】 of an
    « orthography » question)."""
    import re
    import words
    if ex.get("qtype") == "orthography":
        m = re.search(r"【(.*?)】", ex.get("question", ""))
        return m.group(1) if m else ""
    return words.reading_in(ex.get("words"), ex.get("full_sentence", ""), (ex.get("answers") or [""])[0])


def add_jlpt_readings(ex: dict) -> None:
    """Furigana of a JLPT question as in the real test (words above its level) and the kana of each
    choice, shown once answered."""
    import dictionary
    import lexicon
    import words
    if ex.get("words") and words.has_readings(ex["words"]):
        ex["furigana"] = words.exam_furigana(ex["words"], ex.get("level", ""), dictionary.kanji_info())

    def lookup(word):   # the piece of the sentence (ordering), else the dictionary
        found = words.reading_in(ex.get("words"), ex.get("full_sentence", ""), word)
        if found:
            return found
        entry = lexicon.lookup(word) if lexicon.available() else None
        return (entry or {}).get("reading") or tutor.reading(word)
    if ex.get("choices") and ex.get("qtype") != "kanji_reading":
        ex["choice_readings"] = words.choice_readings(ex["choices"], (ex.get("answers") or [""])[0],
                                                      answer_reading(ex), lookup)


def localize(items: list, language: str = None) -> list:
    """Exercises in the interface language: topic title, translation, hint and explanation.
    Exercises store French texts, plus English ones (*_en) when they have them."""
    language = language or lang()
    for ex in items:
        ex["topic_label"] = curriculum.title(ex.get("topic", ""), language)
        if ex.get("qtype") and ex.get("choices"):
            add_jlpt_readings(ex)
        if language != "en":
            continue
        key = ex.get("source_key") or (ex.get("source_url") and "tatoeba:" + ex["source_url"].rsplit("/", 1)[-1])
        ex["translation"] = ex.get("translation_en") or bank_translation(key or "", "en") or ex.get("translation", "")
        ex["hint"] = ex.get("hint_en", "")
        explanation = ex.get("explanation_en")
        if explanation is None:
            explanation = ex.get("explanation", "")
            if ex.get("qtype") in ("kanji_reading", "orthography") or explanation.startswith("Ordre :"):
                for a, b in RULE_EXPLANATION_EN:
                    explanation = explanation.replace(a, b)
                explanation = explanation.replace("Ordre :", "Order:")
            else:
                explanation = ""   # only in French: better nothing than a text the student cannot read
        ex["explanation"] = explanation
    return items


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        try:
            settings.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        except ValueError:
            pass
    return settings


def save_settings(changes: dict) -> dict:
    settings = load_settings()
    keys = dict(settings.get("api_keys") or {})
    for name, key in (changes.pop("api_keys", None) or {}).items():   # merge: one key at a time
        if name in llm.CLOUD:
            if key:
                keys[name] = str(key).strip()
            else:
                keys.pop(name, None)
    settings.update({k: v for k, v in changes.items() if k in DEFAULT_SETTINGS})
    settings["api_keys"] = keys
    llm.API_KEYS.clear()
    llm.API_KEYS.update(keys)
    if "ollama_url" in changes:
        llm.set_ollama_url(settings.get("ollama_url") or "http://localhost:11434")
    if settings.get("language") not in LANGUAGES:
        settings["language"] = "fr"
    SETTINGS_PATH.parent.mkdir(exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return settings


def fill_status() -> dict:
    return {k: (v[-300:] if k == "log" else v) for k, v in FILL.items()}


def run_job(title: str, work) -> dict:
    """Runs work(log, should_stop, db) → number of exercises added, in the background (one job at a time)."""
    with FILL_LOCK:
        if FILL["running"]:
            return fill_status()
        FILL.update(running=True, stop=False, log=[], started=time.strftime("%H:%M:%S"), finished=None,
                    added=None, title=title)

    def log(line):
        FILL["log"].extend(str(line).splitlines() or [""])
        print(line)

    def run():
        db = store.connect(DB_PATH)
        try:
            FILL["added"] = work(log, lambda: FILL["stop"], db)
        except Exception as e:  # keep the server alive, show the error in the page
            log(f"! {type(e).__name__}: {e}")
        finally:
            db.close()
            FILL.update(running=False, finished=time.strftime("%H:%M:%S"))

    threading.Thread(target=run, daemon=True).start()
    return fill_status()


def public_settings() -> dict:
    """Settings for the page: the token is never sent back, only whether one is set."""
    settings = load_settings()
    settings["bank_token_set"] = bool(settings.pop("bank_token", ""))
    settings["api_keys_set"] = {name: bool(key) for name, key in (settings.pop("api_keys", None) or {}).items()}
    settings["defaults"] = {name: c["default"] for name, c in llm.CLOUD.items()}
    settings["local"] = MODEL
    return settings


def chat_model() -> str:
    """The teacher's model: a cloud model chosen in Progress → Teacher, otherwise the local one."""
    chosen = load_settings().get("chat_model") or ""
    return chosen if llm.provider(chosen) != "ollama" else MODEL


def bank_status() -> dict:
    import bank_sync
    state = bank_sync.load_state()
    settings = load_settings()
    return {"url": settings.get("bank_url") or bank_sync.DEFAULT_URL, "last_pull": state.get("last_pull"),
            "last_added": state.get("last_added", 0), "version": state.get("bank_version"),
            "count": state.get("bank_count"), "sent": len(state.get("sent", [])),
            "can_contribute": bool(settings.get("bank_contribute"))}


def start_bank_job(action: str) -> dict:
    settings = load_settings()

    def work(log, should_stop, db):
        import bank_sync
        token = settings.get("bank_token", "")
        if action == "pull":
            return bank_sync.pull(db, settings.get("bank_url") or bank_sync.DEFAULT_URL, token, log=log)
        dest = settings.get("bank_contribute", "")
        if not dest:
            log(tr("Destination d'envoi non réglée (Progrès → Banque partagée).",
                   "No destination set for sending (Progress → Shared bank)."))
            return 0
        bank_sync.contribute(db, dest, token, settings.get("contributor") or "friend", log=log)
        return 0
    return run_job(tr("Banque partagée", "Shared bank"), work)


def start_fill(options: dict) -> dict:
    def work(log, should_stop, db):
        ids = [i for i in options.get("topics", []) if i in curriculum.BY_ID]
        results = fill_reserve.fill(db, target=int(options.get("target", 15)), all_topics=bool(options.get("all")),
                                    ids=ids or None, model=MODEL, log=log, should_stop=should_stop)
        return sum(a for _, a in results)
    return run_job(tr("Remplissage de la réserve", "Filling the reserve"), work)


def start_jlpt_fill(options: dict) -> dict:
    level = str(options.get("level") or load_settings()["jlpt_level"])

    def work(log, should_stop, db):
        import jlpt_questions
        return jlpt_questions.fill(db, level, int(options.get("per_type", 10)), model=MODEL, log=log,
                                   should_stop=should_stop)
    return run_job(tr(f"Questions JLPT {level}", f"JLPT {level} questions"), work)


def jlpt_overview(db, level: str) -> dict:
    import jlpt_questions as jq
    import lexicon
    counts = {t["topic"]: t for t in store.topics(db)}
    types = []
    for qtype in jq.TYPES:
        t = counts.get(jq.topic_title(level, qtype), {"total": 0, "unseen": 0})
        types.append({"type": qtype, "label": jq.LABELS_EN[qtype] if lang() == "en" else jq.LABELS[qtype], "total": t["total"], "unseen": t["unseen"],
                      "exam": jq.EXAM.get(level, {}).get(qtype, 0)})
    return {"level": level, "levels": list(jq.EXAM), "types": types, "exams": store.exams(db),
            "lexicon": lexicon.available(), "kanji": jq.KANJI_PATH.exists()}


def ollama_up() -> bool:
    try:
        with urllib.request.urlopen(llm.OLLAMA_URL + "/api/tags", timeout=2):
            return True
    except Exception:
        return False


def start_maintenance() -> dict:
    """At startup: Anki sync (once a day), then top up the reserve as soon as Ollama answers."""
    def work(log, should_stop, db):
        settings = load_settings()
        if settings["auto_sync"] and anki_available():
            known = tutor.KNOWN_PATH
            synced_today = known.exists() and json.loads(known.read_text(encoding="utf-8")).get("date") == \
                time.strftime("%Y-%m-%d")
            config_changed = (Path("data") / "anki.json").exists() and known.exists() and \
                (Path("data") / "anki.json").stat().st_mtime > known.stat().st_mtime
            if synced_today and not config_changed:
                log(tr("Anki : déjà synchronisé aujourd'hui.", "Anki: already synced today."))
            else:
                log(tr("Synchronisation Anki…", "Syncing Anki…"))
                try:
                    import anki_sync
                    anki_sync.sync(log=log)
                except Exception as e:
                    log(f"! Anki : {e}")
        added = 0
        try:
            import review
            review.revalidate(db, log=log)   # removes exercises that the current rules would not generate
            review.apply_pending(db, log=log)  # reviewed batches dropped in data/reviews/
        except Exception as e:
            log(f"! Review check: {e}")
        if settings.get("bank_auto_sync"):
            try:
                import bank_sync
                bank_sync.pull(db, settings.get("bank_url") or bank_sync.DEFAULT_URL, settings.get("bank_token", ""), log=log)
            except Exception as e:
                log(tr(f"Banque partagée injoignable : {e}", f"Shared bank not reachable: {e}"))
        if settings["auto_fill"] and (Path("data") / "bank.db").exists() and settings.get("local_model") is not False:
            waited = 0
            while not ollama_up() and waited < 900 and not should_stop():
                if waited == 0:
                    log(tr("En attente d'Ollama…", "Waiting for Ollama…"))
                time.sleep(15)
                waited += 15
            if ollama_up() and not should_stop():
                results = fill_reserve.fill(db, target=int(settings["fill_target"]), model=MODEL, log=log,
                                            should_stop=should_stop)
                added += sum(a for _, a in results)
                if settings.get("jlpt_auto_fill"):
                    try:
                        import jlpt_questions
                        added += jlpt_questions.fill(db, settings.get("jlpt_level", "N4"), model=MODEL, log=log,
                                                     should_stop=should_stop)
                    except ImportError:
                        pass
            elif not should_stop():
                log(tr("Ollama ne répond pas : réserve non remplie (bouton « Remplir la réserve » plus tard).",
                       "Ollama is not answering: reserve not filled (use « Fill the reserve » later)."))
        return added
    return run_job(tr("Maintenance au démarrage", "Startup maintenance"), work)


def daily_maintenance() -> None:
    """For an app that stays on (a Raspberry Pi…): the startup maintenance again every day, so new
    exercises of the shared bank arrive without a restart."""
    while True:
        time.sleep(24 * 3600)
        if not setup_needed(load_settings(), 1) and not FILL["running"]:
            start_maintenance()


def anki_available() -> bool:
    """An Anki collection on this computer, or a configuration from an earlier sync."""
    if (Path("data") / "anki.json").exists():
        return True
    try:
        import anki_db
        return bool(anki_db.find_collections())
    except Exception:
        return False


def setup_needed(settings: dict, reserve: int) -> bool:
    """First start: the welcome screen. Existing installs (a reserve already there) skip it."""
    done = settings.get("setup_done")
    return not done if done is not None else reserve == 0


def apply_setup(data: dict) -> dict:
    """Choices of the welcome screen: language, starting level, Anki, local model."""
    teacher = data.get("teacher") or ("local" if data.get("local_model") else "")
    changes = {"setup_done": True, "language": data.get("language") if data.get("language") in LANGUAGES else lang(),
               "updates": data.get("updates") if data.get("updates") in updater.MODES else "notify",
               "local_model": bool(data.get("local_model")), "auto_sync": bool(data.get("anki")),
               "auto_fill": bool(data.get("local_model")), "jlpt_auto_fill": bool(data.get("local_model")),
               "jlpt_level": "N4" if data.get("level") == "N4" else "N5", "bank_auto_sync": True}
    if teacher in llm.CLOUD:   # Claude or ChatGPT: the chat uses it, with the key given on the welcome screen
        changes["chat_model"] = f"{teacher}:{llm.CLOUD[teacher]['default']}"
        if str(data.get("api_key", "")).strip():
            changes["api_keys"] = {teacher: str(data["api_key"]).strip()}
    save_settings(changes)
    db = store.connect(DB_PATH)
    try:
        if data.get("level") == "N4":   # the N5 programme counts as known
            for t in curriculum.TOPICS:
                if t["level"] == "N5":
                    store.set_topic_known(db, t["title"], True)
    finally:
        db.close()
    return start_maintenance()


def status() -> dict:
    ollama = False
    try:
        with urllib.request.urlopen(llm.OLLAMA_URL + "/api/tags", timeout=2) as r:
            names = [m.get("name", "") for m in json.loads(r.read().decode("utf-8")).get("models", [])]
            ollama = True
    except Exception:
        names = []
    db = store.connect(DB_PATH)
    try:
        reserve = db.execute("SELECT COUNT(*) FROM exercises").fetchone()[0]
    finally:
        db.close()
    settings = load_settings()
    model = chat_model()
    cloud = llm.provider(model) != "ollama"
    installed = any(n == MODEL or n.split(":")[0] == MODEL for n in names)
    return {
        "chat_model": model,
        "chat_ready": bool(llm.api_key(llm.provider(model))) if cloud else (ollama and installed),
        "packaged": PACKAGED,
        "version": updater.VERSION,
        "setup": setup_needed(settings, reserve),
        "anki_found": anki_available(),
        "local_model": settings.get("local_model"),
        "ollama": ollama,
        "model": MODEL,
        "model_installed": any(n == MODEL or n.split(":")[0] == MODEL for n in names),
        "bank": (Path("data") / "bank.db").exists(),
        "anki_sync": tutor.KNOWN_PATH.exists(),
        "reserve": reserve,
    }


def watch_reviews(interval: int = 30) -> None:
    """Applies reviewed batches dropped in data/reviews/ while the app runs (see review.py)."""
    import review

    def loop():
        while True:
            time.sleep(interval)
            try:
                if review.REVIEWS_DIR.exists() and any(not p.name.endswith(".applied.json")
                                                       for p in review.REVIEWS_DIR.glob("*.json")):
                    db = store.connect(DB_PATH)
                    try:
                        review.apply_pending(db, log=print)
                    finally:
                        db.close()
            except Exception as e:
                print(f"! Reviewed batch: {e}")
    threading.Thread(target=loop, daemon=True).start()


# ---------------------------------------------------------------------------
# App window (packaged app): the interface opens in its own window, and the app stops when it is closed
# ---------------------------------------------------------------------------

WINDOW = {"ping": None, "closing": None}
CLOSE_GRACE = 10       # seconds after the page is closed: a reload pings again well before
LOST_TIMEOUT = 300     # no sign of the page at all (browser crashed, closed without notice)


def find_app_browser() -> str:
    """Edge (on every Windows 10/11) or Chrome, which can show a page as an app window (--app)."""
    if os.name != "nt":
        return ""
    roots = [os.environ.get(v, "") for v in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
    for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
        for root in roots:
            if root and Path(root, rel).is_file():
                return str(Path(root, rel))
    return ""


def open_app_window(url: str) -> bool:
    """Opens the interface in an app window (no address bar, own taskbar entry). False: use the browser."""
    exe = find_app_browser()
    if not exe:
        return False
    profile = app_home() / "window"   # a profile of its own: a separate window, not a tab of the user's browser
    try:
        import subprocess
        subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1180,860",
                          "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"],
                         close_fds=True)
        return True
    except OSError:
        return False


def open_interface(url: str, window: bool) -> None:
    if not (window and open_app_window(url)):
        webbrowser.open(url)


def watch_window() -> None:
    """Packaged app: stops the server once its window is closed (the page says so when it goes away)."""
    def loop():
        while True:
            time.sleep(2)
            now, ping, closing = time.time(), WINDOW["ping"], WINDOW["closing"]
            if ping is None:
                continue   # the page has not opened yet
            if closing and now - closing > CLOSE_GRACE and ping < closing:
                print("Window closed: stopping.")
                shutdown()
            if now - ping > LOST_TIMEOUT:
                print("No page open for a while: stopping.")
                shutdown()
    threading.Thread(target=loop, daemon=True).start()


# ---------------------------------------------------------------------------
# Updates (updater.py)
# ---------------------------------------------------------------------------

def update_mode() -> str:
    mode = load_settings().get("updates", "notify")
    return mode if mode in updater.MODES else "notify"


def update_status() -> dict:
    return updater.status(update_mode(), PACKAGED)


def install_update() -> None:
    """« Update » button: download if needed, then swap the .exe and start it again."""
    if updater.STATE["state"] == "available":
        updater.download()
    if updater.install(restart=True):
        time.sleep(0.5)   # let the page get its last answer
        os._exit(0)


def shutdown() -> None:
    """Stops the app; a downloaded update (« auto » mode) is installed on the way out."""
    if updater.STATE["state"] == "ready":
        updater.install(restart=False)
    os._exit(0)


def app_home() -> Path:
    """Where the packaged app keeps its data: %LOCALAPPDATA%\\JapaneseCoach (data/ inside)."""
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "JapaneseCoach"
    base.mkdir(parents=True, exist_ok=True)
    return base


def main() -> None:
    global MODEL, DB_PATH
    if PACKAGED:
        os.chdir(app_home())   # every module uses paths relative to data/
    if sys.stdout is None:  # started with pythonw (no console): log to a file
        Path("data").mkdir(exist_ok=True)
        sys.stdout = sys.stderr = open(Path("data") / "server.log", "a", encoding="utf-8", buffering=1)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Starts the Japanese Coach app on http://localhost:8000")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1",
                   help="address to listen on (default 127.0.0.1: this computer only). 0.0.0.0 = the whole network: "
                        "there is no password, so only on a private network such as Tailscale")
    p.add_argument("--ollama", default="",
                   help="Ollama of another computer, e.g. my-pc:11434 (default: the « ollama_url » setting, else localhost)")
    p.add_argument("--model", default=llm.DEFAULT_MODEL, help=f"Ollama model for the chat (default: {llm.DEFAULT_MODEL})")
    p.add_argument("--db", default=None, help="progress database (default: data/coach.db)")
    p.add_argument("--open", action="store_true", help="open the app in the browser")
    p.add_argument("--window", action="store_true", help="open the app in its own window (Edge / Chrome app mode)")
    p.add_argument("--no-maintenance", action="store_true",
                   help="do not sync Anki / fill the reserve at startup (see data/settings.json)")
    args = p.parse_args()
    MODEL, DB_PATH = args.model, args.db
    llm.API_KEYS.update(load_settings().get("api_keys") or {})
    llm.set_ollama_url(args.ollama or load_settings().get("ollama_url") or "")
    url = f"http://localhost:{args.port}"
    if PACKAGED:
        args.open = args.window = True
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError:   # already running (second double-click): just open it
        print(f"Port {args.port} already in use: opening {url}")
        open_interface(url, args.window)
        return
    print(f"✓ Japanese Coach running on {url}  (Ctrl+C to stop)")
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"  Listening on {args.host}:{args.port}: anyone who can reach this address can use the app (no password).")
    if llm.OLLAMA_URL != "http://localhost:11434":
        print(f"  Ollama: {llm.OLLAMA_URL}")
    if args.open or args.window:
        threading.Timer(0.5, lambda: open_interface(url, args.window)).start()
    if PACKAGED:
        watch_window()
    db = store.connect(DB_PATH)
    try:
        first_start = setup_needed(load_settings(), db.execute("SELECT COUNT(*) FROM exercises").fetchone()[0])
    finally:
        db.close()
    if not args.no_maintenance and not first_start:   # on first start, the welcome screen starts it
        start_maintenance()
    if not args.no_maintenance:
        threading.Thread(target=daily_maintenance, daemon=True).start()
    watch_reviews()
    if PACKAGED or os.environ.get("JAPANESE_COACH_UPDATE_URL"):   # the source version is updated with git pull
        updater.start(update_mode(), PACKAGED)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
