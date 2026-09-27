#!/usr/bin/env python3
"""
Shows what is in your Anki collection, to set up the Anki sync.
Anki must be open, with the AnkiConnect add-on (code 2055492159).

    python anki_inspect.py
    python anki_inspect.py --deck "Full Japanese Study Deck"   # only decks whose name contains this

Prints every deck with its card counts (total / reviewed / mature = interval ≥ 21 days),
then, for each note type used, the field names and one sample note.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

ANKI_URL = "http://localhost:8765"


def anki(action: str, **params):
    body = json.dumps({"action": action, "version": 6, "params": params}).encode("utf-8")
    try:
        with urllib.request.urlopen(urllib.request.Request(ANKI_URL, data=body), timeout=60) as r:
            reply = json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError:
        sys.exit("Cannot reach AnkiConnect on localhost:8765. Is Anki open, with AnkiConnect installed?")
    if reply.get("error"):
        sys.exit(f"AnkiConnect error: {reply['error']}")
    return reply["result"]


def quote(deck: str) -> str:
    return '"deck:' + deck.replace('"', '\\"') + '"'


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Shows decks, card counts and note fields of your Anki collection.")
    p.add_argument("--deck", default="", help="only decks whose name contains this text")
    args = p.parse_args()

    decks = sorted(d for d in anki("deckNames") if args.deck.lower() in d.lower())
    print(f"=== {len(decks)} deck(s) ===")
    for deck in decks:
        q = quote(deck)
        total = len(anki("findCards", query=q))
        reviewed = len(anki("findCards", query=f"{q} -is:new"))
        mature = len(anki("findCards", query=f"{q} prop:ivl>=21"))
        print(f"{deck}\n    {total} cards · {reviewed} reviewed · {mature} mature")

    print("\n=== Note types and fields ===")
    note_ids = anki("findNotes", query=" OR ".join(quote(d) for d in decks) if decks else "deck:*")
    seen = set()
    for i in range(0, len(note_ids), 500):
        for note in anki("notesInfo", notes=note_ids[i:i + 500]):
            model = note["modelName"]
            if model in seen:
                continue
            seen.add(model)
            print(f"\n--- {model} ---")
            for name, field in note["fields"].items():
                value = field["value"].replace("\n", " ")
                print(f"  {name}: {value[:80]}")
        if len(seen) >= 10:
            break


if __name__ == "__main__":
    main()
