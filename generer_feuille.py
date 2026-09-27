#!/usr/bin/env python3
"""
Générateur de feuilles de cours + exercices à trous en japonais, via un LLM local (Ollama).

Utilisation :
    python generer_feuille.py --theme "les particules に et で" --niveau N5 --reponses "に,で"
    python generer_feuille.py --theme "la forme en て" --niveau N5 --nb 12 --modele gemma3:12b

--reponses (optionnel) : liste fermée des réponses possibles. Tout exercice dont la réponse
n'est pas dans la liste est écarté, et la liste est affichée sur la feuille.
    python generer_feuille.py --demo          # feuille d'exemple, sans Ollama

La feuille est enregistrée dans le dossier « feuilles/ » (HTML + JSON) puis ouverte
dans ton navigateur. Aucune dépendance : uniquement la bibliothèque standard de Python.
"""

import argparse
import datetime
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/chat"
MODELE_PAR_DEFAUT = "qwen3:14b"
MARQUEUR = "___"
DOSSIER_SORTIE = Path("feuilles")

# ---------------------------------------------------------------------------
# 1. Le format imposé au modèle (sortie structurée JSON)
# ---------------------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {
        "titre": {"type": "string"},
        "cours": {
            "type": "object",
            "properties": {
                "introduction": {"type": "string"},
                "points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "regle": {"type": "string"},
                            "exemples": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "jp": {"type": "string"},
                                        "lecture": {"type": "string"},
                                        "fr": {"type": "string"},
                                    },
                                    "required": ["jp", "lecture", "fr"],
                                },
                            },
                        },
                        "required": ["regle", "exemples"],
                    },
                },
            },
            "required": ["introduction", "points"],
        },
        "vocabulaire": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "mot": {"type": "string"},
                    "lecture": {"type": "string"},
                    "sens": {"type": "string"},
                },
                "required": ["mot", "lecture", "sens"],
            },
        },
        "exercices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "phrase": {"type": "string"},
                    "autres_reponses": {"type": "array", "items": {"type": "string"}},
                    "indice": {"type": "string"},
                    "traduction": {"type": "string"},
                    "explication": {"type": "string"},
                },
                "required": ["phrase", "autres_reponses", "indice", "traduction", "explication"],
            },
        },
    },
    "required": ["titre", "cours", "vocabulaire", "exercices"],
}

# ---------------------------------------------------------------------------
# 2. Le « prof » : prompt système (c'est ici que tu configures ton LLM)
# ---------------------------------------------------------------------------

PROMPT_SYSTEME = """Tu es un professeur de japonais expérimenté qui enseigne à un élève francophone.
Tu es rigoureux : chaque phrase japonaise que tu écris doit être naturelle et grammaticalement correcte.
Toutes les explications, règles, indices et traductions sont en français, clairs et concrets.
Tu respectes strictement le niveau demandé (vocabulaire, kanji et grammaire).
Tu réponds uniquement avec le JSON demandé, sans aucun texte autour."""


def construire_demande(theme: str, niveau: str, nb: int, autorisees: list) -> str:
    if autorisees:
        liste = ", ".join(autorisees)
        regle_cible = (f"- L'élément entre 【 】 doit OBLIGATOIREMENT être exactement l'un de : {liste}.\n"
                       f"  Choisis des phrases où UNE SEULE de ces réponses est correcte, et utilise-les toutes "
                       f"à peu près autant.\n")
    else:
        regle_cible = ""
    return f"""Crée une feuille de cours sur le thème : « {theme} ».
Niveau de l'élève : {niveau}.

Contenu attendu :
- "titre" : un titre court en français.
- "cours" : une introduction de 2 à 4 phrases, puis 2 à 5 points de règle, chacun avec 1 à 3 exemples
  ("jp" = la phrase japonaise, "lecture" = sa lecture en hiragana (かな), JAMAIS en romaji,
  "fr" = la traduction). Chaque exemple doit illustrer la règle sous laquelle il est placé.
- "vocabulaire" : 5 à 10 mots utiles pour ce thème ("mot" en japonais usuel, "lecture" en hiragana
  (JAMAIS en romaji), "sens" en français).
- "exercices" : {nb} exercices à trous.

Règles pour chaque exercice :
- "phrase" : une phrase japonaise COMPLÈTE et correcte, dans laquelle tu entoures de 【 】
  l'élément que l'élève doit retrouver. Exactement UNE paire de 【 】 par phrase.
- L'élément entre 【 】 est TOUJOURS le point de grammaire du thème, et rien d'autre.
  Pour un thème sur des particules : uniquement la particule, jamais le nom ou le verbe à côté.
  Pour un thème sur une conjugaison : uniquement la forme conjuguée.
{regle_cible}- Chaque exercice doit porter sur le thème. Pas d'exercice sur une autre particule ou une autre règle.
- "autres_reponses" : les autres écritures acceptables du même élément (par ex. en kanji ou en kana),
  sinon une liste vide [].
- "indice" : une piste en français qui aide sans donner la réponse.
- "traduction" : la traduction française de la phrase complète.
- "explication" : pourquoi c'est cette réponse, en 1 à 3 phrases, cohérente avec la réponse.
- Varie les phrases et la difficulté, du plus simple au plus difficile.

Exemple de format pour UN exercice (sur un autre thème, la particule を) :
{{"phrase": "毎朝パン【を】食べます。", "autres_reponses": [], "indice": "Qu'est-ce qu'on mange ?",
 "traduction": "Je mange du pain tous les matins.",
 "explication": "を marque le complément d'objet direct : ce qu'on mange."}}"""


# ---------------------------------------------------------------------------
# 3. Appel au modèle local
# ---------------------------------------------------------------------------

def appeler_ollama(modele: str, messages: list, temperature: float) -> str:
    charge = {
        "model": modele,
        "messages": messages,
        "stream": False,
        "format": SCHEMA,
        "options": {"temperature": temperature, "num_ctx": 8192},
    }
    requete = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(charge).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(requete, timeout=900) as reponse:
        donnees = json.loads(reponse.read().decode("utf-8"))
    return donnees["message"]["content"]


def extraire_json(texte: str) -> dict:
    # Certains modèles « réfléchissent » à voix haute : on retire ce passage.
    texte = re.sub(r"<think>.*?</think>", "", texte, flags=re.S).strip()
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut == -1 or fin == -1:
        raise ValueError("aucun JSON trouvé dans la réponse")
    return json.loads(texte[debut : fin + 1])


CROCHETS = re.compile(r"[【［\[]([^】］\]]*)[】］\]]")


def norm(texte: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(texte)))


def nettoyer(feuille: dict, autorisees: list) -> tuple:
    """Transforme les 【réponses】 en trous et écarte les exercices mal formés.
    Renvoie (exercices valides, nombre d'exercices écartés)."""
    autorisees_norm = {norm(a) for a in autorisees}
    valides, ecartes = [], 0
    for ex in feuille.get("exercices", []):
        phrase = str(ex.get("phrase", ""))
        cibles = CROCHETS.findall(phrase)
        # Exactement un élément entre crochets, et pas de trou déjà présent.
        if len(cibles) != 1 or not cibles[0].strip() or "_" in phrase or "＿" in phrase:
            ecartes += 1
            continue
        cible = cibles[0].strip()
        # Avec une liste fermée, la réponse doit en faire partie (ça écarte les
        # exercices où le modèle cache le nom au lieu de la particule, par ex.).
        if autorisees_norm and norm(cible) not in autorisees_norm:
            ecartes += 1
            continue
        autres = [str(r).strip() for r in ex.get("autres_reponses", []) or []]
        autres = [r for r in autres if r and not CROCHETS.search(r)]
        if autorisees_norm:
            autres = [r for r in autres if norm(r) in autorisees_norm and norm(r) == norm(cible)]
        valides.append({
            "phrase": CROCHETS.sub(MARQUEUR, phrase, count=1),
            "phrase_complete": CROCHETS.sub(lambda m: m.group(1), phrase, count=1),
            "reponses": list(dict.fromkeys([cible] + autres)),
            "indice": str(ex.get("indice", "")),
            "traduction": str(ex.get("traduction", "")),
            "explication": str(ex.get("explication", "")),
        })
    return valides, ecartes


def generer(theme: str, niveau: str, nb: int, modele: str, temperature: float,
            autorisees: list, essais: int = 3) -> dict:
    # On en demande un peu plus que nécessaire : certains seront écartés.
    messages = [
        {"role": "system", "content": PROMPT_SYSTEME},
        {"role": "user", "content": construire_demande(theme, niveau, nb + 4, autorisees)},
    ]
    base, exercices, vues = None, [], set()
    for essai in range(1, essais + 1):
        print(f"→ Génération avec {modele} (essai {essai}/{essais})…")
        t0 = time.time()
        try:
            brut = appeler_ollama(modele, messages, temperature)
        except urllib.error.HTTPError as e:
            corps = e.read().decode("utf-8", "replace")
            sys.exit(f"Erreur Ollama ({e.code}) : {corps}\n"
                     f"Le modèle est-il installé ? Essaie : ollama pull {modele}")
        except urllib.error.URLError:
            sys.exit("Impossible de joindre Ollama sur localhost:11434.\n"
                     "Vérifie qu'il est lancé (application Ollama ouverte, ou « ollama serve »).")
        print(f"  réponse reçue en {time.time() - t0:.0f} s")
        try:
            feuille = extraire_json(brut)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"  réponse illisible ({e}), nouvel essai.")
            continue
        if base is None:
            base = feuille  # on garde le cours et le vocabulaire du premier essai réussi
        valides, ecartes = nettoyer(feuille, autorisees)
        for ex in valides:
            if norm(ex["phrase"]) not in vues:
                vues.add(norm(ex["phrase"]))
                exercices.append(ex)
        print(f"  {len(valides)} exercice(s) valide(s), {ecartes} écarté(s) · total : {len(exercices)}/{nb}")
        if len(exercices) >= nb:
            break
    if base is None or not exercices:
        sys.exit("Le modèle n'a produit aucun exercice exploitable. Essaie un autre modèle ou un thème plus précis.")
    base["exercices"] = exercices[:nb]
    return base


# ---------------------------------------------------------------------------
# 4. Feuille d'exemple (pour tester sans Ollama)
# ---------------------------------------------------------------------------

DEMO = {
    "titre": "Les particules は et が",
    "cours": {
        "introduction": "は (prononcé « wa ») indique le thème de la phrase : ce dont on parle. "
                        "が indique le sujet grammatical, souvent une information nouvelle ou mise en avant. "
                        "Les deux se traduisent rarement mot à mot : c'est une question de point de vue.",
        "points": [
            {"regle": "は marque le thème : « en ce qui concerne X… »",
             "exemples": [
                 {"jp": "私は学生です。", "lecture": "わたしはがくせいです。", "fr": "Je suis étudiant(e)."},
                 {"jp": "今日は暑いです。", "lecture": "きょうはあついです。", "fr": "Aujourd'hui, il fait chaud."}]},
            {"regle": "が signale l'existence de quelque chose de nouveau, avec いる / ある",
             "exemples": [
                 {"jp": "公園に犬がいます。", "lecture": "こうえんにいぬがいます。", "fr": "Il y a un chien dans le parc."}]},
            {"regle": "Un mot interrogatif sujet prend toujours が, et la réponse aussi",
             "exemples": [
                 {"jp": "誰が来ましたか。", "lecture": "だれがきましたか。", "fr": "Qui est venu ?"},
                 {"jp": "田中さんが来ました。", "lecture": "たなかさんがきました。", "fr": "C'est M. Tanaka qui est venu."}]},
            {"regle": "Avec 好き, 嫌い, 上手, 分かる…, l'objet de la préférence ou de la capacité prend が",
             "exemples": [
                 {"jp": "私は猫が好きです。", "lecture": "わたしはねこがすきです。", "fr": "J'aime les chats."}]},
        ],
    },
    "vocabulaire": [
        {"mot": "学生", "lecture": "がくせい", "sens": "étudiant(e)"},
        {"mot": "犬", "lecture": "いぬ", "sens": "chien"},
        {"mot": "猫", "lecture": "ねこ", "sens": "chat"},
        {"mot": "好き", "lecture": "すき", "sens": "aimer, apprécier"},
        {"mot": "天気", "lecture": "てんき", "sens": "le temps (météo)"},
        {"mot": "上手", "lecture": "じょうず", "sens": "doué, habile"},
    ],
    "exercices": [
        {"phrase": "わたし___がくせいです。", "reponses": ["は"],
         "indice": "On présente le thème de la phrase.",
         "traduction": "Je suis étudiant(e).",
         "explication": "は marque le thème : « en ce qui me concerne, je suis étudiant ». C'est la structure de base X は Y です."},
        {"phrase": "だれ___きましたか。", "reponses": ["が"],
         "indice": "Le sujet est un mot interrogatif.",
         "traduction": "Qui est venu ?",
         "explication": "Un mot interrogatif (だれ, なに, どれ…) utilisé comme sujet prend toujours が, jamais は."},
        {"phrase": "わたしはねこ___すきです。", "reponses": ["が"],
         "indice": "Regarde le mot à la fin de la phrase.",
         "traduction": "J'aime les chats.",
         "explication": "すき marque ce qu'on aime avec が : わたしは (thème) ねこが (ce qu'on aime) すきです."},
        {"phrase": "あそこにいぬ___います。", "reponses": ["が"],
         "indice": "On signale la présence de quelque chose de nouveau.",
         "traduction": "Il y a un chien là-bas.",
         "explication": "Pour signaler l'existence de quelque chose avec いる / ある, on utilise が : l'information est nouvelle."},
        {"phrase": "きょう___いいてんきですね。", "reponses": ["は"],
         "indice": "On parle d'aujourd'hui comme cadre de la phrase.",
         "traduction": "Il fait beau aujourd'hui, n'est-ce pas ?",
         "explication": "きょう est le thème : « aujourd'hui, (il fait) beau temps ». は pose le cadre de la phrase."},
        {"phrase": "「これはなんですか。」「それ___ペンです。」", "reponses": ["は"],
         "indice": "La réponse reprend la structure de la question.",
         "traduction": "« Qu'est-ce que c'est ? » « C'est un stylo. »",
         "explication": "La question porte sur これ avec は ; la réponse garde le même thème : それはペンです."},
        {"phrase": "どれ___あなたのかばんですか。", "reponses": ["が"],
         "indice": "Encore un mot interrogatif en position de sujet.",
         "traduction": "Lequel est ton sac ?",
         "explication": "どれ est un mot interrogatif sujet : il prend が, comme だれ ou なに."},
        {"phrase": "たなかさんはにほんご___じょうずです。", "reponses": ["が"],
         "indice": "Comme すき, じょうず suit un schéma particulier.",
         "traduction": "M. Tanaka est doué en japonais.",
         "explication": "じょうず marque le domaine de compétence avec が : たなかさんは (thème) にほんごが じょうずです."},
    ],
}

# ---------------------------------------------------------------------------
# 5. Génération de la page HTML interactive
# ---------------------------------------------------------------------------

GABARIT_HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITRE__</title>
<style>
:root{--bg:#faf8f5;--card:#fff;--text:#1f1d1a;--muted:#6b665e;--border:#e6e1d9;--accent:#b8323a;
--ok:#2f7d4f;--ok-bg:#e8f4ec;--ko:#b8323a;--ko-bg:#fbeaea;--hint-bg:#fff7e0}
@media (prefers-color-scheme: dark){:root{--bg:#171614;--card:#211f1c;--text:#ece8e1;--muted:#a39d93;
--border:#35322d;--accent:#e06a70;--ok:#6cc58e;--ok-bg:#1c2e23;--ko:#e98088;--ko-bg:#35201f;--hint-bg:#2e2a1d}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);line-height:1.6;
font-family:system-ui,-apple-system,"Segoe UI","Hiragino Sans","Yu Gothic UI",Meiryo,"Noto Sans JP",sans-serif}
main{max-width:760px;margin:0 auto;padding:32px 16px 80px}
.meta{color:var(--muted);font-size:.9rem}
h1{font-size:1.8rem;margin:.1em 0 .3em}
h2{font-size:1.2rem;margin:2.2rem 0 .6rem;border-bottom:2px solid var(--accent);display:inline-block;padding-bottom:2px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px 18px;margin:12px 0}
.regle{font-weight:600;margin-bottom:.4rem}
.exemple{margin:.6rem 0 .2rem}
.jp{font-size:1.25rem}
.lecture{color:var(--muted);font-size:.9rem}
.fr{color:var(--muted);font-style:italic;font-size:.95rem}
body.sans-lectures .lecture{display:none}
table{width:100%;border-collapse:collapse}
td,th{padding:8px 6px;border-bottom:1px solid var(--border);text-align:left}
th{color:var(--muted);font-weight:500;font-size:.85rem}
td.jp{font-size:1.15rem}
.toolbar{position:sticky;top:0;background:var(--bg);padding:10px 0;display:flex;gap:8px;flex-wrap:wrap;
align-items:center;z-index:5;border-bottom:1px solid var(--border)}
.score{margin-left:auto;font-weight:600}
button{font:inherit;font-size:.9rem;padding:6px 12px;border-radius:8px;border:1px solid var(--border);
background:var(--card);color:var(--text);cursor:pointer}
button:hover{border-color:var(--muted)}
button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.num{color:var(--muted);font-size:.85rem}
.phrase{font-size:1.35rem;margin:.2rem 0 .7rem;line-height:2.2}
.phrase input{font:inherit;font-size:1.2rem;width:6em;padding:0 8px;border:none;border-bottom:2px solid var(--accent);
background:transparent;color:var(--text);text-align:center;outline:none}
.phrase input:focus{background:var(--hint-bg)}
.exo.ok .phrase input{border-color:var(--ok);color:var(--ok)}
.exo.ko .phrase input{border-color:var(--ko)}
.actions{display:flex;gap:8px;flex-wrap:wrap}
.indice{background:var(--hint-bg);padding:8px 12px;border-radius:8px;margin-top:10px}
.feedback{margin-top:10px;padding:10px 12px;border-radius:8px}
.exo.ok .feedback{background:var(--ok-bg)}
.exo.ko .feedback{background:var(--ko-bg)}
[hidden]{display:none!important}
.fin{text-align:center;font-size:1.1rem;margin-top:24px}
.exo > .lecture, .exo > .fr{margin:-.4rem 0 .6rem}
.source{color:var(--muted);font-size:.8rem}
.choix{margin:.4rem 0 0}
.choix span{display:inline-block;font-size:1.2rem;padding:0 10px;margin:0 4px;border:1px solid var(--border);
border-radius:6px;background:var(--card)}
</style>
</head>
<body>
<main id="app"></main>
<script>
const DATA = /*__DATA__*/;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const norm = s => String(s).normalize("NFKC").replace(/[\s。、．，.,!！?？「」]/g, "");
const app = document.getElementById("app");
const meta = DATA.meta || {};

let html = `<p class="meta">${esc(meta.niveau || "")}${meta.date ? " · " + esc(meta.date) : ""}${meta.modele ? " · " + esc(meta.modele) : ""}</p>
<h1>${esc(DATA.titre)}</h1>`;

if (DATA.cours && (DATA.cours.introduction || (DATA.cours.points || []).length)) {
  html += `<h2>Cours</h2>`;
  if (DATA.cours.introduction) html += `<div class="card"><p>${esc(DATA.cours.introduction)}</p></div>`;
  for (const p of DATA.cours.points || []) {
    html += `<div class="card"><div class="regle">${esc(p.regle)}</div>`;
    for (const e of p.exemples || []) {
      html += `<div class="exemple"><div class="jp" lang="ja">${esc(e.jp)}</div>
        <div class="lecture" lang="ja">${esc(e.lecture)}</div><div class="fr">${esc(e.fr)}</div></div>`;
    }
    html += `</div>`;
  }
}

if (DATA.vocabulaire && DATA.vocabulaire.length) {
  html += `<h2>Vocabulaire</h2><div class="card"><table><tr><th>Mot</th><th class="lecture">Lecture</th><th>Sens</th></tr>`;
  for (const v of DATA.vocabulaire) {
    html += `<tr><td class="jp" lang="ja">${esc(v.mot)}</td><td class="lecture" lang="ja">${esc(v.lecture)}</td><td>${esc(v.sens)}</td></tr>`;
  }
  html += `</table></div>`;
}

html += `<h2>Exercices</h2>`;
if (meta.reponses_possibles && meta.reponses_possibles.length) {
  html += `<p class="choix">Réponses possibles : ${meta.reponses_possibles.map(r => `<span lang="ja">${esc(r)}</span>`).join("")}</p>`;
}
html += `
<div class="toolbar">
  <button id="btn-lectures">Masquer les lectures</button>
  <button id="btn-tout">Tout vérifier</button>
  <button id="btn-reset">Recommencer</button>
  <span class="score" id="score"></span>
</div>`;

DATA.exercices.forEach((ex, i) => {
  const [avant, apres] = ex.phrase.split("___");
  html += `<div class="card exo" id="exo-${i}">
    <div class="num">Exercice ${i + 1}</div>
    <div class="phrase" lang="ja">${esc(avant)}<input lang="ja" autocomplete="off" spellcheck="false" data-i="${i}" aria-label="Réponse exercice ${i + 1}">${esc(apres)}</div>
    ${ex.lecture ? `<div class="lecture" lang="ja">${esc(ex.lecture)}</div>` : ""}
    ${ex.traduction_avant ? `<div class="fr">${esc(ex.traduction)}</div>` : ""}
    <div class="actions">
      <button class="primary" data-action="verifier" data-i="${i}">Vérifier</button>
      <button data-action="indice" data-i="${i}"${ex.indice ? "" : " hidden"}>Indice</button>
      <button data-action="reponse" data-i="${i}" hidden>Voir la réponse</button>
    </div>
    <div class="indice" hidden>💡 ${esc(ex.indice)}</div>
    <div class="feedback" hidden></div>
  </div>`;
});
html += `<p class="fin" id="fin" hidden></p>`;
app.innerHTML = html;
document.title = DATA.titre;

const etat = DATA.exercices.map(() => ({ premier: null, resolu: false }));
const exo = i => document.getElementById("exo-" + i);
const champ = i => exo(i).querySelector("input");

function corrige(i, message) {
  const ex = DATA.exercices[i];
  const autres = ex.reponses.length > 1 ? `<br>Réponses acceptées : <span lang="ja">${ex.reponses.map(esc).join(" / ")}</span>` : "";
  const trad = ex.traduction && !ex.traduction_avant ? `<br><span class="fr">${esc(ex.traduction)}</span>` : "";
  const expl = ex.explication ? `<br>${esc(ex.explication)}` : "";
  const src = ex.source_url ? `<br><a class="source" href="${esc(ex.source_url)}" target="_blank" rel="noopener">${esc(ex.source || "source")}</a>` : "";
  return `${message}${autres}${trad}${expl}${src}`;
}

function verifier(i) {
  const st = etat[i];
  if (st.resolu) return true;
  const ex = DATA.exercices[i], box = exo(i), val = champ(i).value;
  if (!norm(val)) { champ(i).focus(); return false; }
  const ok = ex.reponses.some(r => norm(r) === norm(val));
  if (st.premier === null) st.premier = ok;
  box.classList.toggle("ok", ok);
  box.classList.toggle("ko", !ok);
  const fb = box.querySelector(".feedback");
  fb.hidden = false;
  if (ok) {
    st.resolu = true;
    champ(i).readOnly = true;
    box.querySelector('[data-action="reponse"]').hidden = true;
    fb.innerHTML = corrige(i, "✓ <strong>Correct !</strong>");
  } else {
    box.querySelector('[data-action="reponse"]').hidden = false;
    fb.innerHTML = "✗ Pas tout à fait. Réessaie, demande un indice ou affiche la réponse.";
  }
  majScore();
  return ok;
}

function montrerReponse(i) {
  const st = etat[i], box = exo(i);
  if (st.premier === null) st.premier = false;
  st.resolu = true;
  champ(i).value = DATA.exercices[i].reponses[0];
  champ(i).readOnly = true;
  box.classList.remove("ok"); box.classList.add("ko");
  box.querySelector('[data-action="reponse"]').hidden = true;
  const fb = box.querySelector(".feedback");
  fb.hidden = false;
  fb.innerHTML = corrige(i, `Réponse : <strong lang="ja">${esc(DATA.exercices[i].reponses[0])}</strong>`);
  majScore();
}

function majScore() {
  const n = etat.length;
  const bons = etat.filter(s => s.premier === true).length;
  const faits = etat.filter(s => s.resolu).length;
  document.getElementById("score").textContent = `${bons} / ${n} du premier coup · ${faits}/${n} terminés`;
  const fin = document.getElementById("fin");
  fin.hidden = faits < n;
  if (faits === n) fin.textContent = `Terminé ! ${bons} / ${n} du premier coup.`;
}

function suivant(i) {
  for (let j = i + 1; j < etat.length; j++) if (!etat[j].resolu) { champ(j).focus(); return; }
}

app.addEventListener("click", e => {
  const b = e.target.closest("button[data-action]");
  if (!b) return;
  const i = +b.dataset.i;
  if (b.dataset.action === "verifier" && verifier(i)) suivant(i);
  if (b.dataset.action === "indice") exo(i).querySelector(".indice").hidden = false;
  if (b.dataset.action === "reponse") montrerReponse(i);
});

app.addEventListener("keydown", e => {
  if (e.target.tagName !== "INPUT" || e.key !== "Enter") return;
  if (e.isComposing || e.keyCode === 229) return; // Entrée sert à valider la saisie japonaise (IME)
  e.preventDefault();
  const i = +e.target.dataset.i;
  if (verifier(i)) suivant(i);
});

document.getElementById("btn-lectures").onclick = e => {
  const cache = document.body.classList.toggle("sans-lectures");
  e.target.textContent = cache ? "Afficher les lectures" : "Masquer les lectures";
};
document.getElementById("btn-tout").onclick = () => {
  etat.forEach((s, i) => { if (!s.resolu && norm(champ(i).value)) verifier(i); });
};
document.getElementById("btn-reset").onclick = () => {
  etat.forEach((s, i) => {
    s.premier = null; s.resolu = false;
    const box = exo(i);
    box.classList.remove("ok", "ko");
    champ(i).value = ""; champ(i).readOnly = false;
    box.querySelector(".feedback").hidden = true;
    box.querySelector(".indice").hidden = true;
    box.querySelector('[data-action="reponse"]').hidden = true;
  });
  majScore();
  champ(0).focus();
};

majScore();
</script>
</body>
</html>
"""


def ecrire_html(feuille: dict, chemin: Path) -> None:
    donnees = json.dumps(feuille, ensure_ascii=False).replace("</", "<\\/")
    titre = (feuille.get("titre", "Feuille de japonais")
             .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    page = GABARIT_HTML.replace("/*__DATA__*/", donnees).replace("__TITRE__", titre)
    chemin.write_text(page, encoding="utf-8")


def nom_fichier(theme: str) -> str:
    slug = re.sub(r"[^\w]+", "-", theme.lower()).strip("-")[:40] or "feuille"
    horodatage = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    return f"{horodatage}_{slug}"


# ---------------------------------------------------------------------------
# 6. Point d'entrée
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # affichage du japonais dans la console Windows
    except Exception:
        pass

    p = argparse.ArgumentParser(description="Génère une feuille de cours + exercices à trous en japonais.")
    p.add_argument("--theme", help="le point à travailler, ex. « les particules に et で »")
    p.add_argument("--niveau", default="N5", help="niveau de l'élève (N5, N4… ou une description libre)")
    p.add_argument("--nb", type=int, default=10, help="nombre d'exercices (défaut : 10)")
    p.add_argument("--modele", default=MODELE_PAR_DEFAUT, help=f"modèle Ollama (défaut : {MODELE_PAR_DEFAUT})")
    p.add_argument("--temperature", type=float, default=0.7, help="créativité du modèle (0 = strict, 1 = varié)")
    p.add_argument("--reponses", default="",
                   help="liste fermée des réponses possibles, séparées par des virgules, ex. « に,で »")
    p.add_argument("--demo", action="store_true", help="génère la feuille d'exemple, sans Ollama")
    p.add_argument("--pas-ouvrir", action="store_true", help="ne pas ouvrir la feuille dans le navigateur")
    args = p.parse_args()

    autorisees = [r.strip() for r in re.split(r"[,，、/\s]+", args.reponses) if r.strip()]

    if args.demo:
        feuille = json.loads(json.dumps(DEMO))
        theme, modele = "demo particules wa ga", "exemple"
        autorisees = autorisees or ["は", "が"]
    else:
        if not args.theme:
            p.error("indique un thème avec --theme, ou utilise --demo")
        feuille = generer(args.theme, args.niveau, args.nb, args.modele, args.temperature, autorisees)
        theme, modele = args.theme, args.modele

    feuille["meta"] = {
        "theme": theme,
        "niveau": args.niveau,
        "modele": modele,
        "date": datetime.date.today().isoformat(),
        "reponses_possibles": autorisees,
    }

    DOSSIER_SORTIE.mkdir(exist_ok=True)
    base = DOSSIER_SORTIE / nom_fichier(theme)
    base.with_suffix(".json").write_text(json.dumps(feuille, ensure_ascii=False, indent=2), encoding="utf-8")
    chemin_html = base.with_suffix(".html")
    ecrire_html(feuille, chemin_html)

    print(f"✓ Feuille créée : {chemin_html}  ({len(feuille['exercices'])} exercices)")
    if not args.pas_ouvrir:
        webbrowser.open(chemin_html.resolve().as_uri())


if __name__ == "__main__":
    main()
