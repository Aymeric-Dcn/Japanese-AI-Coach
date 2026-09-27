#!/usr/bin/env python3
"""
Construit la banque de phrases à partir de Tatoeba (phrases réelles, traduites).

    python construire_banque.py            # japonais avec traduction française
    python construire_banque.py --anglais  # + phrases qui n'ont qu'une traduction anglaise

Étapes :
  1. télécharge les exports Tatoeba dans data/tatoeba/ (une seule fois) ;
  2. garde les phrases japonaises qui ont une traduction ;
  3. découpe chaque phrase avec SudachiPy (mots, catégorie grammaticale, lecture) ;
  4. enregistre tout dans data/banque.db (SQLite).

Dépendances : pip install -r requirements.txt
Données : Tatoeba (https://tatoeba.org), licence CC BY 2.0 FR.
"""

import argparse
import bz2
import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

DOSSIER_DATA = Path("data")
DOSSIER_TATOEBA = DOSSIER_DATA / "tatoeba"
CHEMIN_BANQUE = DOSSIER_DATA / "banque.db"
URL_BASE = "https://downloads.tatoeba.org/exports/per_language"

FICHIERS = {
    "jpn": f"{URL_BASE}/jpn/jpn_sentences.tsv.bz2",
    "fra": f"{URL_BASE}/fra/fra_sentences.tsv.bz2",
    "jpn-fra": f"{URL_BASE}/jpn/jpn-fra_links.tsv.bz2",
    "eng": f"{URL_BASE}/eng/eng_sentences.tsv.bz2",
    "jpn-eng": f"{URL_BASE}/jpn/jpn-eng_links.tsv.bz2",
}

# Catégories qui ne comptent pas comme des « mots » (ponctuation, espaces).
NON_MOTS = {"補助記号", "空白", "記号"}


# ---------------------------------------------------------------------------
# Téléchargement
# ---------------------------------------------------------------------------

def telecharger(nom: str) -> Path:
    url = FICHIERS[nom]
    chemin = DOSSIER_TATOEBA / url.rsplit("/", 1)[1]
    if chemin.exists() and chemin.stat().st_size > 0:
        return chemin
    DOSSIER_TATOEBA.mkdir(parents=True, exist_ok=True)
    print(f"↓ {chemin.name}…", end="", flush=True)
    temporaire = chemin.with_suffix(".part")
    with urllib.request.urlopen(url, timeout=120) as reponse, open(temporaire, "wb") as f:
        total = int(reponse.headers.get("Content-Length") or 0)
        recu = 0
        while bloc := reponse.read(1 << 16):
            f.write(bloc)
            recu += len(bloc)
            if total:
                print(f"\r↓ {chemin.name} {recu * 100 // total:3d} %", end="", flush=True)
    temporaire.replace(chemin)
    print(f"\r↓ {chemin.name} ✓ ({recu / 1e6:.1f} Mo)      ")
    return chemin


def lire_tsv(chemin: Path):
    with bz2.open(chemin, "rt", encoding="utf-8") as f:
        for ligne in f:
            yield ligne.rstrip("\n").split("\t")


def lire_phrases(chemin: Path, ids_voulus=None) -> dict:
    """Fichier « id  langue  texte » → {id: texte}."""
    phrases = {}
    for champs in lire_tsv(chemin):
        if len(champs) < 3:
            continue
        i = int(champs[0])
        if ids_voulus is None or i in ids_voulus:
            phrases[i] = champs[2]
    return phrases


def lire_liens(chemin: Path) -> dict:
    """Fichier « id_japonais  id_traduction » → {id_japonais: premier id_traduction}."""
    liens = {}
    for champs in lire_tsv(chemin):
        if len(champs) >= 2:
            liens.setdefault(int(champs[0]), int(champs[1]))
    return liens


# ---------------------------------------------------------------------------
# Analyse morphologique
# ---------------------------------------------------------------------------

def creer_analyseur():
    try:
        from sudachipy import Dictionary, SplitMode
    except ImportError:
        sys.exit("SudachiPy n'est pas installé. Lance : pip install -r requirements.txt")
    try:
        dico = Dictionary(dict="core")
    except TypeError:  # anciennes versions de SudachiPy
        dico = Dictionary(dict_type="core")
    # SudachiPy ≥ 0.7 : tokenizer() ; versions précédentes : create()
    tokenizer = dico.tokenizer() if hasattr(dico, "tokenizer") else dico.create()
    return lambda texte: tokenizer.tokenize(texte, SplitMode.C)


def en_hiragana(texte: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in texte)


def analyser(analyseur, texte: str) -> list:
    """Chaque mot : [forme écrite, catégorie, sous-catégorie, lecture en hiragana, forme du dictionnaire]."""
    mots = []
    for m in analyseur(texte):
        pos = m.part_of_speech()
        surface = m.surface()
        lecture = m.reading_form() if pos[0] not in NON_MOTS else ""
        mots.append([surface, pos[0], pos[1], en_hiragana(lecture) or surface, m.dictionary_form()])
    return mots


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Construit data/banque.db à partir de Tatoeba.")
    p.add_argument("--anglais", action="store_true",
                   help="garder aussi les phrases qui n'ont qu'une traduction anglaise (téléchargement plus gros)")
    args = p.parse_args()

    analyseur = creer_analyseur()  # on vérifie SudachiPy avant de télécharger quoi que ce soit

    t0 = time.time()
    liens_fr = lire_liens(telecharger("jpn-fra"))
    liens_en = lire_liens(telecharger("jpn-eng")) if args.anglais else {}
    ids_jp = set(liens_fr) | set(liens_en)

    print("Lecture des phrases…")
    japonais = lire_phrases(telecharger("jpn"), ids_jp)
    francais = lire_phrases(telecharger("fra"), set(liens_fr.values()))
    anglais = lire_phrases(telecharger("eng"), set(liens_en.values())) if args.anglais else {}

    DOSSIER_DATA.mkdir(exist_ok=True)
    if CHEMIN_BANQUE.exists():
        CHEMIN_BANQUE.unlink()
    db = sqlite3.connect(CHEMIN_BANQUE)
    db.execute("""CREATE TABLE phrases (
        id INTEGER PRIMARY KEY,   -- identifiant Tatoeba de la phrase japonaise
        jp TEXT NOT NULL,
        fr TEXT,
        en TEXT,
        nb_mots INTEGER NOT NULL,
        mots TEXT NOT NULL        -- JSON : [[forme, catégorie, sous-catégorie, lecture, forme du dictionnaire], …]
    )""")

    print(f"Analyse de {len(japonais)} phrases…")
    lignes = []
    for n, (i, jp) in enumerate(japonais.items(), 1):
        fr = francais.get(liens_fr.get(i))
        en = anglais.get(liens_en.get(i))
        if not (fr or en):
            continue
        mots = analyser(analyseur, jp)
        nb_mots = sum(1 for m in mots if m[1] not in NON_MOTS)
        lignes.append((i, jp, fr, en, nb_mots, json.dumps(mots, ensure_ascii=False)))
        if n % 5000 == 0:
            print(f"  {n}/{len(japonais)}")
    db.executemany("INSERT INTO phrases VALUES (?, ?, ?, ?, ?, ?)", lignes)
    db.execute("CREATE INDEX idx_nb_mots ON phrases(nb_mots)")
    db.commit()
    db.close()

    avec_fr = sum(1 for l in lignes if l[2])
    print(f"✓ {CHEMIN_BANQUE} : {len(lignes)} phrases ({avec_fr} avec traduction française) "
          f"en {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
