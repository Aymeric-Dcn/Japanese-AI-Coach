"""
Reads an Anki collection straight from its file (collection.anki2), without Anki running.

The file is copied first (with its -wal journal if any) and the copy is opened read-only,
so your collection is never touched, even if Anki is open.

    notes = AnkiCollection.open().notes()      # [{id, type, fields{name: value}, tags, decks, max_interval, reviewed}]

Works with the current Anki format (tables notetypes / fields / decks) and the older one
(everything in the col table as JSON).
"""

import json
import os
import platform
import shutil
import sqlite3
import tempfile
from pathlib import Path


def anki_base_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Anki2"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Anki2"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "Anki2"


def find_collections(base: Path = None) -> list:
    """[(profile name, path)] of every profile's collection, most recently modified first."""
    base = base or anki_base_dir()
    if not base.exists():
        return []
    found = [(p.parent.name, p) for p in base.glob("*/collection.anki2") if p.parent.name != "addons21"]
    return sorted(found, key=lambda x: x[1].stat().st_mtime, reverse=True)


class AnkiCollection:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._tmp = tempfile.mkdtemp(prefix="anki-copy-")
        copy = Path(self._tmp) / "collection.anki2"
        shutil.copy2(self.path, copy)
        for suffix in ("-wal", "-shm"):
            extra = Path(str(self.path) + suffix)
            if extra.exists():
                shutil.copy2(extra, Path(str(copy) + suffix))
        self.db = sqlite3.connect(copy)
        self.db.row_factory = sqlite3.Row
        self.models, self.decks = self._load_models_and_decks()

    @classmethod
    def open(cls, path: str = None, profile: str = None) -> "AnkiCollection":
        if path:
            return cls(Path(path))
        found = find_collections()
        if profile:
            found = [f for f in found if f[0] == profile]
        if not found:
            raise FileNotFoundError(f"No Anki collection found in {anki_base_dir()}"
                                    + (f" for profile « {profile} »" if profile else ""))
        return cls(found[0][1])

    def close(self) -> None:
        self.db.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _has_table(self, name: str) -> bool:
        return bool(self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())

    def _load_models_and_decks(self) -> tuple:
        """models: {id: {"name", "fields": [names in order]}}, decks: {id: name with '::'}."""
        models, decks = {}, {}
        if self._has_table("notetypes") and self._has_table("fields"):
            for r in self.db.execute("SELECT id, name FROM notetypes"):
                models[r["id"]] = {"name": r["name"], "fields": []}
            for r in self.db.execute("SELECT ntid, ord, name FROM fields ORDER BY ntid, ord"):
                if r["ntid"] in models:
                    models[r["ntid"]]["fields"].append(r["name"])
        else:
            col = self.db.execute("SELECT models FROM col").fetchone()
            for mid, m in json.loads(col["models"]).items():
                models[int(mid)] = {"name": m["name"],
                                    "fields": [f["name"] for f in sorted(m["flds"], key=lambda f: f["ord"])]}
        if self._has_table("decks"):
            for r in self.db.execute("SELECT id, name FROM decks"):
                decks[r["id"]] = r["name"].replace("\x1f", "::")
        else:
            col = self.db.execute("SELECT decks FROM col").fetchone()
            for did, d in json.loads(col["decks"]).items():
                decks[int(did)] = d["name"]
        return models, decks

    def note_types(self) -> dict:
        """{note type name: number of notes}"""
        counts = {}
        for r in self.db.execute("SELECT mid, COUNT(*) AS n FROM notes GROUP BY mid"):
            name = self.models.get(r["mid"], {}).get("name", str(r["mid"]))
            counts[name] = r["n"]
        return counts

    def notes(self, note_types: list = None, limit: int = None) -> list:
        """Notes with their fields, tags, decks and the largest interval of their cards (in days).
        `limit`: stop after that many matching notes (for samples)."""
        wanted = None
        if note_types is not None:
            wanted = {mid for mid, m in self.models.items() if m["name"] in note_types}
            if not wanted:
                return []
        cards = {}
        for r in self.db.execute("SELECT nid, did, ivl, type FROM cards"):
            c = cards.setdefault(r["nid"], {"decks": set(), "ivl": 0, "reviewed": False})
            c["decks"].add(self.decks.get(r["did"], ""))
            c["ivl"] = max(c["ivl"], r["ivl"] if r["ivl"] > 0 else 0)   # negative = seconds (learning)
            c["reviewed"] = c["reviewed"] or r["type"] != 0              # type 0 = new card
        result = []
        for r in self.db.execute("SELECT id, mid, tags, flds FROM notes"):
            if limit and len(result) >= limit:
                break
            if wanted is not None and r["mid"] not in wanted:
                continue
            model = self.models.get(r["mid"], {"name": "?", "fields": []})
            values = r["flds"].split("\x1f")
            names = model["fields"] + [f"field{i}" for i in range(len(model["fields"]), len(values))]
            c = cards.get(r["id"], {"decks": set(), "ivl": 0, "reviewed": False})
            result.append({
                "id": r["id"], "type": model["name"], "fields": dict(zip(names, values)),
                "tags": r["tags"].split(), "decks": sorted(c["decks"]),
                "max_interval": c["ivl"], "reviewed": c["reviewed"],
            })
        return result
