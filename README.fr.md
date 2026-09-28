# Japanese Coach AI

*[English version](README.md)*

Un prof de japonais personnel qui tourne **entièrement sur ton ordinateur** : une petite app web avec des exercices quotidiens construits à partir de vraies phrases selon un programme JLPT N5 → N4, la répétition espacée de tes erreurs, des questions type JLPT et des examens blancs chronométrés, et un chat avec un prof animé par un LLM local ([Ollama](https://ollama.com)).

> Projet d'apprentissage : apprendre le japonais, et apprendre à configurer un LLM en même temps.

## Comment ça marche

```
Tatoeba ──► build_bank.py ──► data/bank.db (vraies phrases, découpées par SudachiPy)
Anki ─────► anki_sync.py ───► data/known.json, lexicon.db, grammar.json, kanji.json
(fichier lu directement, Anki peut être fermé ; n'importe quel deck)   + jlpt_data.py : listes JLPT libres
                    │
                    ▼
            make_exercises.py --save   (choisit les phrases, fait le trou,
                    │                   Qwen écarte les douteuses et explique)
                    ▼
            data/coach.db ◄──► server.py + web/  →  http://localhost:8000
            (réserve, réponses,         Session · JLPT · Prof (chat) · Progrès
             révisions, chat)
```

- **Des exercices sur de vraies phrases** : la réponse est le texte d'origine, les lectures viennent de l'analyseur ; le LLM n'invente rien, il filtre et explique.
- **À ton niveau** : avec la synchronisation Anki, seulement des phrases dont tu connais les mots (ou tous sauf un : « i+1 »).
- **Répétition espacée** : un exercice raté revient en fin de session et le lendemain ; un exercice réussi revient après 1, 3, 7, 16 jours, puis de plus en plus tard.
- **JLPT** : questions 漢字読み, 表記, 文脈規定, 文法形式 et 並べ替え ★ par niveau, entraînement avec correction immédiate ou examens blancs chronométrés notés par section.
- **Chat avec le prof**, trois modes : « Prof » (questions, explications, corrections), « Conversation » (japonais simple avec traduction et corrections, 7 situations), « Quiz » (sur tes points faibles). Avant de répondre, le prof reçoit des références fiables : tes fiches de grammaire Anki, les fiches du programme, ton lexique, de vraies phrases Tatoeba.
- **Sans rien faire** : l'app peut démarrer avec Windows ; à chaque démarrage elle synchronise Anki (une fois par jour) et complète les exercices.

## Installation

Configuration testée : Windows, RTX 4070 Super (12 Go VRAM), 32 Go RAM.

1. **Ollama** : installer depuis [ollama.com/download](https://ollama.com/download), puis un modèle :
   ```
   ollama pull qwen3:14b
   ```
2. **Python 3.9+** : [python.org](https://www.python.org/downloads/) (cocher *Add python.exe to PATH*), puis :
   ```
   pip install -r requirements.txt
   ```
3. **Clavier japonais** : Paramètres → Heure et langue → Langue et région → ajouter *Japonais*. Basculer avec `Windows + Espace`.
4. **Anki** (facultatif) : installer le module [AnkiConnect](https://ankiweb.net/shared/info/2055492159) (Outils → Greffons → Obtenir des greffons, code `2055492159`).

## Démarrer

```
python build_bank.py                       # une fois : télécharger et analyser Tatoeba
python jlpt_data.py                        # une fois : listes JLPT libres (niveau des mots)
python anki_sync.py                        # tes mots connus, lexique, grammaire (Anki peut être fermé)
python install_autostart.py                # facultatif : lancer l'app avec Windows, en arrière-plan
python server.py --open                    # l'app, sur http://localhost:8000
```

Puis dans l'app : **Progrès → Remplir la réserve** (ou `python fill_reserve.py` dans un terminal). Des exercices sont ajoutés aux thèmes en cours (environ 5 s chacun avec Qwen) ; les sessions sont ensuite instantanées. Relance `anki_sync.py` quand ton Anki avance.

### Le programme

`curriculum.py` liste 18 thèmes dans l'ordre d'apprentissage, JLPT N5 puis N4. La session du jour propose les révisions de tout, plus des nouveaux exercices des **deux thèmes en cours**. Un thème est validé à 80 % de réussite sur ses 10 à 20 dernières réponses, ou d'office après 5 réponses justes d'affilée ; « Je maîtrise déjà » dans l'onglet Progrès le valide à la main. Le thème suivant se débloque alors.

`fill_reserve.py` complète les thèmes en cours et le suivant (15 exercices non vus par thème par défaut, le double pour un point faible) : `--target 25`, `--all`, `--topics wa-ga,past`, `--no-llm`.

**Entraînement libre** (onglet Session) : choisis n'importe quels thèmes (« Toutes les particules », « Tout N4 »…) ; le « Mode difficile » masque les réponses possibles.

### Thèmes (`--preset`)

`python make_exercises.py --list-presets` les affiche tous :

| Preset | Thème |
| --- | --- |
| `wa-ga`, `wo-ga`, `ni-de`, `ni-e`, `wa-mo`, `to-ya`, `kara-made` | particules N5 (le trou est l'une des deux) |
| `te-form`, `past`, `negative`, `masu`, `tai` | conjugaisons N5 (le verbe est caché, sa forme du dictionnaire et sa lecture sont affichées) |
| `volitional`, `nagara`, `ba`, `tara`, `causative`, `noni-node` | N4 |

Thèmes sur mesure : `--targets "に,で" --pos 格助詞 --title "…"` pour les particules, `--form te` pour les conjugaisons.

### Options de `make_exercises.py`

| Option | Rôle | Défaut |
| --- | --- | --- |
| `--preset` / `--targets` / `--form` | ce qu'on travaille | — |
| `--save` | ajouter à la réserve de l'app (sinon, une feuille HTML est créée) | — |
| `--count` | nombre d'exercices | `10` |
| `--known` | seulement des phrases construites avec tes mots Anki | — |
| `--max-unknown` | avec `--known` : mots inconnus autorisés par phrase (affichés « Nouveau ») | `0` |
| `--known-kanji` | avec `--known` : tous les kanji doivent aussi être connus | — |
| `--min-words` / `--max-words` | longueur des phrases (≈ difficulté) | `3` / `12` |
| `--pos` | catégorie grammaticale exigée, ex. `格助詞` — évite le で de 読んで | selon le preset |
| `--any-context` | particules : accepter aussi すぐに, には, でも… (par défaut, seulement « nom + particule ») | — |
| `--no-llm` | pas de vérification ni d'explication (instantané) | — |
| `--english` | accepter les phrases traduites seulement en anglais (après `build_bank.py --english`) | — |
| `--level`, `--model`, `--seed` | niveau pour les explications, modèle Ollama, sélection reproductible | `N5`, `qwen3:14b`, aléatoire |

### L'app (`server.py`)

`python server.py [--open] [--port 8000] [--model qwen3:14b]`, puis http://localhost:8000.

- **Session** : « Programme du jour » (révisions + nouveaux exercices des thèmes en cours) ou « Entraînement libre » (thèmes au choix). Entrée = vérifier / suivant.
- **Prof** : le chat. Il faut qu'Ollama tourne ; l'état en haut à droite indique s'il est joignable.
- **Progrès** : travail du jour, série de jours, révisions de demain, taux de réussite, le programme (état de chaque thème, « Je maîtrise déjà »), « Remplir la réserve ».

Tout est enregistré dans `data/coach.db` (SQLite). Rien ne quitte ton ordinateur.

### Anki (`anki_sync.py`)

Le fichier de ta collection (`%APPDATA%\Anki2\<profil>\collection.anki2`) est copié puis lu directement : Anki peut être fermé, et rien n'y est jamais écrit. Le premier lancement détecte quels types de notes contiennent des mots, des kanji et de la grammaire, et l'enregistre dans `data/anki.json` ; `python anki_sync.py --setup` montre ce qui a été détecté, et tu peux modifier le fichier (rôle `ignore` pour ignorer un type de note). Ça marche avec n'importe quel deck, plusieurs decks, ou la collection d'un ami (`--collection chemin`). `--source ankiconnect` passe par le module à la place.

### JLPT (`jlpt_questions.py`, onglet JLPT)

`python jlpt_questions.py --level N4` (ou « Générer des questions » dans l'app) ajoute 10 questions de chaque type pour le niveau. Le niveau d'une question = le niveau JLPT de ses mots (sous-paquets JLPT de ton deck Anki, ou listes libres de `jlpt_data.py`). 表記 a besoin de fiches kanji avec on'yomi (Anki). 文法形式 et 文脈規定 sont vérifiés par le LLM (aucun autre choix ne doit convenir). Règles contre les questions ambiguës ou trop faciles : une phrase par question (une question ne donne jamais la réponse d'une autre) ; mauvaises lectures construites comme au vrai test (autre on'yomi du kanji, voyelle longue ↔ courte, son voisé, っ) ; mauvaises graphies avec des kanji de même lecture de niveau N5–N3 qui ne forment pas un vrai mot ; pas de question de kanji sur les mots qui s'écrivent d'habitude en kana (事) ; les paires de particules souvent toutes deux correctes (は/が, に/へ, と/や…) ne sont jamais proposées ensemble ; les formes verbales qui conviendraient aussi (着て / 着たら / 着れば) sont écartées ; le 並べ替え ne garde que des morceaux dont l'ordre est imposé par la grammaire. Examen blanc : nombre de questions par type comme au vrai test (sans compréhension écrite), 1 minute par question, score par section, erreurs renvoyées dans les révisions.

### Erreurs, annulation et révisions à la main

En session : **↶ Annuler ma réponse** (ou Ctrl+Z) oublie un mauvais clic ou une faute de frappe et remet la révision comme avant ; sur un nouvel exercice, il revient au précédent. **En fait je ne maîtrise pas** transforme une bonne réponse due à la chance en erreur (l'exercice revient en fin de session et demain). **Ne plus proposer** suspend un exercice ; **⚑ Signaler une erreur** retire pour de bon un exercice faux ou ambigu (il ne sera plus jamais généré). Dans Progrès → **Révisions** : tous les exercices avec leur prochaine révision, filtre par thème ou par texte, et pour ceux cochés : revoir aujourd'hui, suspendre, réactiver ou signaler ; « jamais vus » ajoute des exercices de la réserve à tes révisions.

### Langue (français / anglais)

L'app fonctionne en français ou en anglais : sélecteur en haut à droite (enregistré dans `data/settings.json`). L'interface, les titres et fiches des thèmes, le prof (consignes, situations de conversation, références) et les traductions des phrases suivent ce choix. Les nouveaux exercices sont générés avec un indice et une explication dans les deux langues ; les anciens n'ont que l'explication en français, masquée en anglais. Les traductions anglaises viennent de Tatoeba : `python build_bank.py` les garde désormais (à relancer une fois ; `--french-only` pour l'ancien comportement).

### Contrôle qualité (`review.py`)

```
python review.py revalidate             # revérifie la réserve avec les règles actuelles (fait aussi à chaque démarrage)
python review.py export --unseen > lot.json
python review.py reject 123 456 --reason "は et が possibles"
python review.py import relu.json       # retraits, corrections, nouvelles questions
```

Quand les règles s'améliorent, la réserve se nettoie au démarrage suivant : les exercices qui ne seraient plus générés sont retirés (et ne reviendront pas), les réponses acceptées sont mises à jour (に et へ tous deux justes avec 行く). Pour une relecture humaine, on exporte un lot, on le relit (toi, ou Claude), et on dépose le fichier relu dans `data/reviews/` : l'app l'applique au démarrage. Les thèmes de particules dont les deux réponses conviennent souvent ne gardent que les phrases où la grammaire tranche : は/が (が dans une subordonnée, 誰が, existence ; は avant un mot interrogatif), は/も (la traduction dit « aussi »), を/が (les deux acceptés avec たい et la forme potentielle), に/へ et と/や (les deux acceptés quand les deux sont justes).

### Démarrage en arrière-plan (`install_autostart.py`)

Ajoute un lanceur dans le dossier Démarrage de Windows : `pythonw server.py` tourne sans fenêtre ; ouvre http://localhost:8000. Au démarrage, le serveur synchronise Anki (une fois par jour), attend Ollama, puis complète la réserve et les questions JLPT (cases à cocher dans Progrès, ou `data/settings.json`). Journal : `data/server.log`. Pour l'enlever : `--uninstall`.

### Mesurer le LLM (`evaluate.py`)

```
python evaluate.py                    # 29 cas écrits à la main dans eval/particle_cases.json
python evaluate.py --model qwen3:8b --runs 3
```

Mesure à quelle fréquence la vérification garde les bons exercices et écarte les phrases ambiguës et les expressions figées. À relancer après chaque changement de prompt ou de modèle, et à noter dans `notes/log.md`.

### Autres outils

- `generate_sheet.py` : cours + exercices entièrement écrits par le LLM (première version du projet, moins fiable).
- `anki_inspect.py` : liste les paquets Anki, le nombre de cartes et les champs.

## Organisation du projet

```
server.py           l'app : serveur web + API JSON (bibliothèque standard uniquement)
web/                l'interface (index.html, app.css, app.js)
store.py            base de progression : réserve, réponses, révisions, chat
srs.py              intervalles de répétition espacée
curriculum.py       le programme : thèmes N5 → N4, règles de progression, fiches de grammaire
jlpt_questions.py   QCM type JLPT par niveau ; conjugate.py : conjugueur de verbes
knowledge.py        références pour le chat (fiches, lexique, vraies phrases)
anki_db.py          lecture d'une collection Anki ;  lexicon.py : niveau et sens des mots
jlpt_data.py        listes JLPT libres ;  install_autostart.py : démarrage avec Windows
fill_reserve.py     complète la réserve en suivant le programme
tutor.py            le prof du chat : prompt, contexte de l'élève, analyse des phrases
llm.py              client Ollama (réponses structurées, streaming)
build_bank.py       Tatoeba → SudachiPy → data/bank.db
make_exercises.py   exercices depuis la banque → réserve (--save) ou feuille HTML
anki_sync.py        mots et kanji connus dans Anki → data/known.json
evaluate.py, eval/  jeu de tests pour mesurer la vérification du LLM
review.py           contrôle qualité de la réserve (revérifier, exporter, retirer, importer)
generate_sheet.py   feuille générée par le LLM ;  sheet.py : feuilles HTML
notes/log.md        journal des tests (en anglais)
```

## Feuille de route

- [x] Feuilles d'exercices à trous générées par un LLM local
- [x] **Banque de phrases** : Tatoeba + SudachiPy, trous exacts, le LLM filtre et explique
- [x] **Synchronisation Anki** : phrases construites avec mes mots (i+1)
- [x] Thèmes de particules et de **conjugaison** (forme en て, passé, négatif, ます, たい)
- [x] **App locale** : sessions quotidiennes, **répétition espacée**, progrès
- [x] **Chat** avec le prof (explications, correction de mes phrases, questions sur un exercice)
- [x] **Jeu de tests** pour mesurer la vérification du LLM
- [ ] Améliorer la vérification grâce au jeu de tests (prompt, modèle)
- [x] Anki sans Anki (fichier de collection), n'importe quel deck, import du lexique et de la grammaire
- [x] **Questions JLPT** (5 types) par niveau, entraînement et examens blancs chronométrés
- [x] Chat avec références (grammaire, lexique, vraies phrases) et modes conversation / quiz
- [x] Démarrage avec Windows, synchronisation Anki et remplissage quotidiens
- [ ] Compréhension écrite (読解) et orale
- [ ] Vérification du vocabulaire avec [JMdict](https://www.edrdg.org/jmdict/j_jmdict.html)
- [x] **Programme** N5 → N4 avec progression, entraînement libre, « Je maîtrise déjà »
- [x] Remplir la réserve depuis l'app
- [ ] D'autres types d'exercices (traduction, remise en ordre, écoute)

## Sources de données et droits

Le dépôt ne contient que du code, des prompts et de la documentation. Les données téléchargées ou personnelles (`data/`, `sources/`, bases SQLite, feuilles générées) sont exclues par le `.gitignore`. Aucun contenu tiré de manuels sous droits ne doit être publié ici.

Sources libres : Tatoeba (CC BY 2.0 FR), open-anki-jlpt-decks (MIT) tiré des listes JLPT de Jonathan Waller sur tanos.co.uk (CC BY), JMdict / KANJIDIC (CC BY-SA 4.0, EDRDG, prévu). Tes propres decks Anki restent sur ton ordinateur (`data/`, jamais publié).
