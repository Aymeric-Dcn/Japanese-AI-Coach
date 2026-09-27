#!/usr/bin/env python3
"""
Shows what is in your Anki collection, to set up the Anki sync.
Anki must be open, with the AnkiConnect add-on (code 2055492159).

    python anki_inspect.py
    python anki_inspect.py --deck "Full Japanese Study Deck"   # only decks whose name contains this

Prints every deck with its card counts (total / mature = interval ≥ 21 days),
then, for each note type used in those decks, its note count, field names and one sample note.
Only one sample note per note type is read, so it stays fast on big collections.
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
        with urllib.request.urlopen(urllib.request.Request(ANKI_URL, data=body), timeout=120) as r:
            reply = json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError:
        sys.exit("Cannot reach AnkiConnect on localhost:8765. Is Anki open, with AnkiConnect installed?")
    if reply.get("error"):
        sys.exit(f"AnkiConnect error: {reply['error']}")
    return reply["result"]


def deck_query(deck: str) -> str:
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
    if not decks:
        sys.exit("No matching deck.")

    print(f"=== {len(decks)} deck(s) ===", flush=True)
    stats = {s["name"]: s for s in anki("getDeckStats", decks=decks).values()}
    for deck in decks:
        total = stats.get(deck, {}).get("total_in_deck", "?")
        mature = len(anki("findCards", query=f"{deck_query(deck)} prop:ivl>=21"))
        print(f"{deck}\n    {total} cards · {mature} mature", flush=True)

    # Top-level decks only (a deck query already includes its subdecks).
    tops = [d for d in decks if not any(d.startswith(other + "::") for other in decks)]
    scope = "(" + " OR ".join(deck_query(d) for d in tops) + ")"

    print("\n=== Note types and fields ===", flush=True)
    for model in anki("modelNames"):
        ids = anki("findNotes", query=f'{scope} "note:{model}"')
        if not ids:
            continue
        note = anki("notesInfo", notes=[ids[0]])[0]
        print(f"\n--- {model} ({len(ids)} notes) ---")
        for name, field in note["fields"].items():
            value = field["value"].replace("\n", " ")
            print(f"  {name}: {value[:80]}")
        print(f"  tags: {' '.join(note.get('tags', []))[:120]}", flush=True)


if __name__ == "__main__":
    main()
