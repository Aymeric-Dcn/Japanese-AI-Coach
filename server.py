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
    GET  /api/session?new=10&topic=…   today's exercises: reviews due, then new ones
    POST /api/answer                   {id, correct, answer} → next review date
    GET  /api/stats                    progress numbers
    GET  /api/chat/history?conversation=…
    POST /api/chat                     {conversation, message, exercise?} → streamed NDJSON {"delta": …}
"""

import argparse
import json
import mimetypes
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import llm
import store
import tutor

WEB_DIR = Path(__file__).resolve().parent / "web"
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
        if ctype.startswith("text/") or ctype in ("application/javascript",):
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
                return self.send_file(WEB_DIR / "index.html")
            if url.path.startswith("/static/"):
                name = url.path[len("/static/"):]
                if "/" in name or name.startswith("."):
                    return self.send_json({"error": "not found"}, 404)
                return self.send_file(WEB_DIR / name)
            if url.path == "/api/status":
                return self.send_json(status())
            db = store.connect(DB_PATH)
            try:
                if url.path == "/api/session":
                    items = store.session(db, new_limit=int(query.get("new", 10)), topic=query.get("topic") or None)
                    return self.send_json({"items": items, "stats": store.stats(db)})
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
            if url.path == "/api/answer":
                db = store.connect(DB_PATH)
                try:
                    result = store.record_answer(db, int(data["id"]), bool(data.get("correct")),
                                                 str(data.get("answer", ""))[:100])
                    return self.send_json({"schedule": result, "stats": store.stats(db)})
                finally:
                    db.close()
            if url.path == "/api/chat":
                return self.chat(data)
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
        messages = tutor.build_messages(db, conversation, message, data.get("exercise"))

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()  # no Content-Length: the connection closes at the end (HTTP/1.0)

        def emit(obj):
            self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()

        answer = []
        try:
            for piece in llm.chat_stream(MODEL, messages):
                answer.append(piece)
                emit({"delta": piece})
            store.add_message(db, conversation, "user", message)
            store.add_message(db, conversation, "assistant", "".join(answer))
            emit({"done": True})
        except llm.OllamaUnavailable:
            emit({"error": "Ollama ne répond pas. Lance l'application Ollama, puis réessaie."})
        except urllib.error.HTTPError as e:
            emit({"error": f"Erreur Ollama {e.code}. Le modèle {MODEL} est-il installé ? (ollama pull {MODEL})"})
        except (BrokenPipeError, ConnectionResetError):
            pass  # the page was closed
        finally:
            db.close()


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
    return {
        "ollama": ollama,
        "model": MODEL,
        "model_installed": any(n == MODEL or n.split(":")[0] == MODEL for n in names),
        "bank": (Path("data") / "bank.db").exists(),
        "anki_sync": tutor.KNOWN_PATH.exists(),
        "reserve": reserve,
    }


def main() -> None:
    global MODEL, DB_PATH
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Starts the Japanese Coach app on http://localhost:8000")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--model", default=llm.DEFAULT_MODEL, help=f"Ollama model for the chat (default: {llm.DEFAULT_MODEL})")
    p.add_argument("--db", default=None, help="progress database (default: data/coach.db)")
    p.add_argument("--open", action="store_true", help="open the app in the browser")
    args = p.parse_args()
    MODEL, DB_PATH = args.model, args.db

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"✓ Japanese Coach running on {url}  (Ctrl+C to stop)")
    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
