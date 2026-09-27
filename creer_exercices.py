#!/usr/bin/env python3
"""
Crée une feuille d'exercices à trous à partir de la banque de vraies phrases (data/banque.db).

    python creer_exercices.py --cibles "に,で" --pos 格助詞 --titre "Les particules に et で"
    python creer_exercices.py --cibles "は,が" --pos 助詞 --nb 15 --max-mots 10
    python creer_exercices.py --cibles "に,で" --pos 格助詞 --sans-llm

Contrairement à generer_feuille.py, le modèle n'invente rien :
  - les phrases viennent de Tatoeba, la réponse est le mot d'origine (certaine) ;
  - les lectures viennent de l'analyseur morphologique ;
  - le LLM (Ollama) sert seulement à écarter les phrases où une autre réponse serait
    aussi correcte, et à écrire un indice et une explication. Avec --sans-llm, il n'est pas utilisé.

Construire la banque d'abord : python construire_banque.py
"""

import argparse
import datetime
import json
import random
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from generer_feuille import DOSSIER_SORTIE, MARQUEUR, ecrire_html, nom_fichier

CHEMIN_BANQUE = Path("data") / "banque.db"
OLLAMA_URL = "http://localhost:11434/api/chat"
MODELE_PAR_DEFAUT = "qwen3:14b"
NON_MOTS = {"補助記号", "空白", "記号"}


def norm(texte: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(texte)))


# ---------------------------------------------------------------------------
# 1. Chercher les phrases candidates dans la banque
# ---------------------------------------------------------------------------

def mot_correspond(mot: list, cibles: set, pos: str) -> bool:
    surface, cat, sous_cat = mot[0], mot[1], mot[2]
    if norm(surface) not in cibles:
        return False
    return not pos or pos in (cat, sous_cat)


AVANT_PARTICULE = {"名詞", "代名詞", "接尾辞"}   # la particule doit suivre un nom
PARTICULES_COLLEES = {"は", "も"}                  # には, では, にも, でも…


def contexte_simple(mots: list, k: int) -> bool:
    """Pour une particule : on garde les cas « nom + particule » simples.
    Écarte すぐに / 親切に (après un adverbe ou un adjectif) et には / でも (particules composées)."""
    if mots[k][1] != "助詞":
        return True  # le filtre ne concerne que les particules
    precedent = next((m for m in reversed(mots[:k]) if m[1] != "空白"), None)
    suivant = next((m for m in mots[k + 1:] if m[1] != "空白"), None)
    if precedent is None or precedent[1] not in AVANT_PARTICULE:
        return False
    if suivant is not None and suivant[1] == "助詞" and suivant[0] in PARTICULES_COLLEES:
        return False
    return True


def candidats(cibles: list, pos: str, min_mots: int, max_mots: int, francais_seul: bool,
              tout_contexte: bool = False) -> dict:
    """Renvoie {cible: [exercice, …]} pour les phrases qui contiennent exactement UNE des cibles."""
    if not CHEMIN_BANQUE.exists():
        sys.exit(f"Banque introuvable ({CHEMIN_BANQUE}). Lance d'abord : python construire_banque.py")
    ensemble = {norm(c) for c in cibles}
    par_cible = {norm(c): [] for c in cibles}
    db = sqlite3.connect(CHEMIN_BANQUE)
    requete = "SELECT id, jp, fr, en, mots FROM phrases WHERE nb_mots BETWEEN ? AND ?"
    if francais_seul:
        requete += " AND fr IS NOT NULL"
    for id_, jp, fr, en, mots_json in db.execute(requete, (min_mots, max_mots)):
        mots = json.loads(mots_json)
        positions = [k for k, m in enumerate(mots) if mot_correspond(m, ensemble, pos)]
        if len(positions) != 1:
            continue  # aucune cible, ou plusieurs (trou ambigu)
        k = positions[0]
        if not tout_contexte and not contexte_simple(mots, k):
            continue
        cible = norm(mots[k][0])
        avant = "".join(m[0] for m in mots[:k])
        apres = "".join(m[0] for m in mots[k + 1:])
        lecture = "".join(m[3] for m in mots[:k]) + MARQUEUR + "".join(m[3] for m in mots[k + 1:])
        par_cible[cible].append({
            "phrase": avant + MARQUEUR + apres,
            "phrase_complete": jp,
            "reponses": [mots[k][0]],
            "lecture": lecture,
            "traduction": fr or en or "",
            "traduction_avant": True,
            "indice": "",
            "explication": "",
            "source": f"Tatoeba #{id_}",
            "source_url": f"https://tatoeba.org/fr/sentences/show/{id_}",
        })
    db.close()
    return par_cible


def melanger_equilibre(par_cible: dict, graine) -> list:
    """Alterne les cibles (に, で, に, で…) pour que la feuille soit équilibrée."""
    rng = random.Random(graine)
    listes = [rng.sample(v, len(v)) for v in par_cible.values() if v]
    ordre = []
    while any(listes):
        for l in listes:
            if l:
                ordre.append(l.pop())
    return ordre


# ---------------------------------------------------------------------------
# 2. Vérification et explications par le LLM local
# ---------------------------------------------------------------------------

SCHEMA_VERIF = {
    "type": "object",
    "properties": {
        "alternatives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reponse": {"type": "string"},
                    "phrase": {"type": "string"},
                    "correcte": {"type": "boolean"},
                },
                "required": ["reponse", "phrase", "correcte"],
            },
        },
        "indice": {"type": "string"},
        "explication": {"type": "string"},
    },
    "required": ["alternatives", "indice", "explication"],
}

PROMPT_SYSTEME = """Tu es un professeur de japonais rigoureux qui enseigne à un élève francophone.
Tu écris en français, de façon claire et concrète. Tu réponds uniquement avec le JSON demandé."""


def demande_verif(ex: dict, cibles: list, niveau: str) -> str:
    bonne = ex["reponses"][0]
    autres = [c for c in cibles if norm(c) != norm(bonne)]
    return f"""Voici une vraie phrase japonaise (corpus Tatoeba) où un mot a été remplacé par {MARQUEUR} :
{ex["phrase"]}
Phrase complète : {ex["phrase_complete"]}
Traduction : {ex["traduction"]}
La réponse d'origine est « {bonne} ». Niveau de l'élève : {niveau}.

1. "alternatives" : pour CHAQUE autre réponse possible ({", ".join(autres) or "aucune"}), écris la phrase
   obtenue en la mettant à la place de {MARQUEUR} ("phrase"), puis indique dans "correcte" si cette phrase
   est à la fois grammaticale, naturelle pour un Japonais ET fidèle à la traduction ci-dessus.
   Sois exigeant : une phrase maladroite, rare ou qui change le sens n'est PAS correcte.
2. "indice" : une piste courte en français qui aide à trouver « {bonne} » sans la donner.
3. "explication" : en 1 à 3 phrases, pourquoi « {bonne} » est la bonne réponse ici."""


def appeler_ollama(modele: str, messages: list, sans_reflexion: bool = True) -> str:
    charge = {"model": modele, "messages": messages, "stream": False, "format": SCHEMA_VERIF,
              "options": {"temperature": 0.2}}
    if sans_reflexion:
        charge["think"] = False  # plus rapide avec les modèles qui « réfléchissent » (qwen3)
    requete = urllib.request.Request(OLLAMA_URL, data=json.dumps(charge).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(requete, timeout=300) as r:
            return json.loads(r.read().decode("utf-8"))["message"]["content"]
    except urllib.error.HTTPError as e:
        if e.code == 400 and sans_reflexion:  # modèle qui ne gère pas l'option « think »
            return appeler_ollama(modele, messages, sans_reflexion=False)
        raise


def verifier(ex: dict, cibles: list, niveau: str, modele: str) -> tuple:
    """Renvoie (gardée ?, raison si écartée)."""
    messages = [{"role": "system", "content": PROMPT_SYSTEME},
                {"role": "user", "content": demande_verif(ex, cibles, niveau)}]
    brut = appeler_ollama(modele, messages)
    brut = re.sub(r"<think>.*?</think>", "", brut, flags=re.S)
    try:
        reponse = json.loads(brut[brut.find("{"): brut.rfind("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return False, "réponse illisible"
    bonne = norm(ex["reponses"][0])
    ensemble = {norm(c) for c in cibles}
    for alt in reponse.get("alternatives", []) or []:
        if not isinstance(alt, dict):
            continue
        r = norm(alt.get("reponse", ""))
        if r in ensemble and r != bonne and alt.get("correcte") is True:
            return False, f"« {alt.get('phrase', r)} » jugée correcte aussi"
    ex["indice"] = str(reponse.get("indice", "")).strip()
    ex["explication"] = str(reponse.get("explication", "")).strip()
    return True, ""


# ---------------------------------------------------------------------------
# 3. Point d'entrée
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Crée une feuille d'exercices à trous à partir de vraies phrases.")
    p.add_argument("--cibles", required=True, help="mots à faire retrouver, séparés par des virgules, ex. « に,で »")
    p.add_argument("--pos", default="",
                   help="catégorie grammaticale exigée (SudachiPy), ex. 格助詞 (particule de cas), 助詞 (toute particule)")
    p.add_argument("--titre", default="", help="titre de la feuille")
    p.add_argument("--nb", type=int, default=10, help="nombre d'exercices (défaut : 10)")
    p.add_argument("--min-mots", type=int, default=3, help="longueur minimale des phrases, en mots")
    p.add_argument("--max-mots", type=int, default=12, help="longueur maximale des phrases, en mots")
    p.add_argument("--niveau", default="N5", help="niveau de l'élève, pour les explications")
    p.add_argument("--modele", default=MODELE_PAR_DEFAUT, help=f"modèle Ollama (défaut : {MODELE_PAR_DEFAUT})")
    p.add_argument("--sans-llm", action="store_true", help="ne pas utiliser Ollama (pas de vérification ni d'explication)")
    p.add_argument("--anglais", action="store_true", help="accepter les phrases traduites seulement en anglais")
    p.add_argument("--tout-contexte", action="store_true",
                   help="pour les particules : accepter aussi すぐに, には, でも… (écartés par défaut)")
    p.add_argument("--graine", type=int, default=None, help="pour retrouver la même sélection de phrases")
    p.add_argument("--pas-ouvrir", action="store_true", help="ne pas ouvrir la feuille dans le navigateur")
    args = p.parse_args()

    cibles = [c.strip() for c in re.split(r"[,，、/\s]+", args.cibles) if c.strip()]
    par_cible = candidats(cibles, args.pos, args.min_mots, args.max_mots, not args.anglais,
                          args.tout_contexte)
    for c, liste in par_cible.items():
        print(f"  {c} : {len(liste)} phrase(s) candidate(s)")
    ordre = melanger_equilibre(par_cible, args.graine)
    if not ordre:
        sys.exit("Aucune phrase trouvée. Essaie d'élargir --max-mots, de retirer --pos, ou ajoute --anglais.")

    retenus, ecartes = [], 0
    if args.sans_llm:
        retenus = ordre[: args.nb]
    else:
        print(f"→ Vérification et explications avec {args.modele}…")
        t0 = time.time()
        for ex in ordre:
            if len(retenus) >= args.nb or ecartes >= args.nb * 4:
                break
            try:
                ok, raison = verifier(ex, cibles, args.niveau, args.modele)
            except urllib.error.URLError:
                sys.exit("Impossible de joindre Ollama sur localhost:11434. Lance Ollama, ou utilise --sans-llm.")
            if ok:
                retenus.append(ex)
                print(f"  ✓ {len(retenus)}/{args.nb}  {ex['phrase_complete']}")
            else:
                ecartes += 1
                print(f"  ✗ écartée : {ex['phrase_complete']}  ({raison})")
        print(f"  {len(retenus)} retenue(s), {ecartes} écartée(s) en {time.time() - t0:.0f} s")
    if not retenus:
        sys.exit("Aucun exercice retenu.")

    random.Random(args.graine).shuffle(retenus)  # que l'ordre ne trahisse pas l'alternance
    titre = args.titre or f"Exercices : {' / '.join(cibles)}"
    feuille = {
        "titre": titre,
        "exercices": retenus,
        "meta": {
            "theme": titre,
            "niveau": args.niveau,
            "modele": "phrases Tatoeba" + ("" if args.sans_llm else f" · {args.modele}"),
            "date": datetime.date.today().isoformat(),
            "reponses_possibles": cibles,
        },
    }

    DOSSIER_SORTIE.mkdir(exist_ok=True)
    base = DOSSIER_SORTIE / nom_fichier("banque-" + "-".join(cibles))
    base.with_suffix(".json").write_text(json.dumps(feuille, ensure_ascii=False, indent=2), encoding="utf-8")
    chemin_html = base.with_suffix(".html")
    ecrire_html(feuille, chemin_html)
    print(f"✓ Feuille créée : {chemin_html}  ({len(retenus)} exercices)")
    if not args.pas_ouvrir:
        webbrowser.open(chemin_html.resolve().as_uri())


if __name__ == "__main__":
    main()
