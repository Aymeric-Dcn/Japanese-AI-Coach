# Guide d'utilisation

*[English version](guide.md) · [Retour au README](../README.fr.md)*

## Le programme

`curriculum.py` liste 23 thèmes dans l'ordre d'apprentissage, JLPT N5 puis N4. La session du jour propose les révisions de tout, plus des nouveaux exercices des **deux thèmes en cours**. Un thème est validé à 80 % de réussite sur ses 10 à 20 dernières réponses, ou d'office après 5 réponses justes d'affilée ; « Je maîtrise déjà » dans l'onglet Progrès le valide à la main. Le thème suivant se débloque alors.

`fill_reserve.py` complète les thèmes en cours et le suivant (15 exercices non vus par thème par défaut, le double pour un point faible) : `--target 25`, `--all`, `--topics wa-ga,past`, `--no-llm`.

**Entraînement libre** (onglet Session) : choisis n'importe quels thèmes (« Toutes les particules », « Tout N4 »…) ; le « Mode difficile » masque les réponses possibles.

## Thèmes (`--preset`)

`python make_exercises.py --list-presets` les affiche tous :

| Preset | Thème |
| --- | --- |
| `wa-ga`, `wo-ga`, `ni-de`, `ni-e`, `wa-mo`, `to-ya`, `kara-made` | particules N5 (le trou est l'une des deux) |
| `te-form`, `past`, `negative`, `masu`, `tai` | conjugaisons N5 (le verbe est caché, sa forme du dictionnaire et sa lecture sont affichées) |
| `relative-ga`, `relative-form` | propositions relatives N5 : が (jamais は) pour le sujet de la proposition, quand la phrase a déjà son thème (これは私が書いた手紙です) ; la forme simple du verbe devant le nom (昨日買った本) |
| `word-order` | N5 : remettre la phrase dans l'ordre d'après la traduction (voir plus bas) |
| `volitional`, `nagara`, `ba`, `tara`, `causative`, `noni-node` | N4 |
| `mae-ato`, `temo` | subordonnées N4 : 行く前に (toujours la forme du dictionnaire), 食べた後で (toujours le passé), 降っても (même si) |

Les relatives, 前に / 後で et ても n'ont pas besoin de modèle : le trou, l'indice et l'explication viennent de règles (`clauses.py`).

**Ordre des mots** (`word_order.py`) : la traduction est affichée et la phrase est coupée en morceaux (un mot avec ses particules), mélangés ; tu cliques dessus dans l'ordre (Retour arrière reprend le dernier). L'ordre japonais est libre pour les morceaux qui portent leur particule : toute réponse avec le prédicat à la fin est juste, et l'ordre le plus courant s'affiche quand le tien est différent. Pour que ce soit vrai, seules des phrases simples sont utilisées : un seul prédicat, et ce qui précise un nom (私の, この, 大きい) collé à lui.

Thèmes sur mesure : `--targets "に,で" --pos 格助詞 --title "…"` pour les particules, `--form te` pour les conjugaisons.

## Options de `make_exercises.py`

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
| `--english` | accepter aussi les phrases traduites dans une seule langue (par défaut, français et anglais sont exigés, pour que les exercices puissent aller dans la banque partagée) | — |
| `--level`, `--model`, `--seed` | niveau pour les explications, modèle Ollama, sélection reproductible | `N5`, `qwen3:14b`, aléatoire |

## L'app (`server.py`)

`python server.py [--open] [--port 8000] [--model qwen3:14b]`, puis http://localhost:8000.

- **Session** : « Programme du jour » (révisions + nouveaux exercices des thèmes en cours) ou « Entraînement libre » (thèmes au choix). Entrée = vérifier / suivant.
- **Mots de la phrase** : touche / clique un mot pour ouvrir sa fiche, comme une petite page de jisho.org : forme du dictionnaire (食べた → 食べる), lecture, sens, niveau JLPT, « courant », s'il est dans ton deck Anki, et pour chaque kanji ses sens, lectures on / kun, niveau JLPT, année d'école et nombre de traits, avec un lien vers Jisho. Le trou et la réponse ne sont jamais cliquables avant que tu répondes ; après, toute la phrase l'est. Les sens viennent de l'API de Jisho via l'app (gardés dans `data/dictionary.db` ; hors ligne : ton deck et les kanji seulement), les kanji de KANJIDIC (`resources/kanji_info.json`, sans réseau). Pas pendant les examens JLPT chronométrés.
- **Lectures** : furigana au-dessus des kanji (plus la phrase entière en kana), cachés au début : « Afficher la lecture » les montre, et l'app retient ton choix. Le verbe à conjuguer montre sa lecture en le touchant. Les questions JLPT gardent les lectures que donne le vrai test.
- **Traduction** : cachée au début (« Voir la traduction »), pour essayer d'abord de comprendre la phrase ; elle s'affiche de toute façon avec la réponse. « Toujours afficher la traduction » sur l'écran de session enlève ça. Les exercices « remettre dans l'ordre » l'affichent toujours.
- **Prof** : le chat. Il utilise le modèle local (Ollama lancé), ou Claude / ChatGPT : Progrès → « Le prof (modèle d'IA) », choisis le fournisseur, colle ta clé d'API (console.anthropic.com ou platform.openai.com ; une séance de chat coûte quelques centimes avec les petits modèles). La clé est gardée dans `data/settings.json` et jamais renvoyée à la page ; avec un fournisseur cloud, tes messages du chat partent chez lui. La génération d'exercices reste locale. L'état en haut à droite indique quel prof répond et s'il est joignable.
- **Progrès** : travail du jour, série de jours, révisions de demain, taux de réussite, le programme (état de chaque thème, « Je maîtrise déjà »), « Remplir la réserve ».

Tout est enregistré dans `data/coach.db` (SQLite). Rien ne quitte ton ordinateur (sauf les messages du chat si tu choisis un prof en ligne).

## Anki (`anki_sync.py`)

Le fichier de ta collection (`%APPDATA%\Anki2\<profil>\collection.anki2`) est copié puis lu directement : Anki peut être fermé, et rien n'y est jamais écrit. Le premier lancement détecte quels types de notes contiennent des mots, des kanji et de la grammaire, et l'enregistre dans `data/anki.json` ; `python anki_sync.py --setup` montre ce qui a été détecté, et tu peux modifier le fichier (rôle `ignore` pour ignorer un type de note). Ça marche avec n'importe quel deck, plusieurs decks, ou la collection d'un ami (`--collection chemin`). `--source ankiconnect` passe par le module à la place.

## JLPT (`jlpt_questions.py`, onglet JLPT)

`python jlpt_questions.py --level N4` (ou « Générer des questions » dans l'app) ajoute 10 questions de chaque type pour le niveau. Le niveau d'une question = le niveau JLPT de ses mots (sous-paquets JLPT de ton deck Anki, ou listes libres de `jlpt_data.py`). 表記 a besoin de fiches kanji avec on'yomi (Anki). 文法形式 et 文脈規定 sont vérifiés par le LLM (aucun autre choix ne doit convenir). Règles contre les questions ambiguës ou trop faciles : une phrase par question (une question ne donne jamais la réponse d'une autre) ; mauvaises lectures construites comme au vrai test (autre on'yomi du kanji, voyelle longue ↔ courte, son voisé, っ) ; mauvaises graphies avec des kanji de même lecture de niveau N5–N3 qui ne forment pas un vrai mot ; pas de question de kanji sur les mots qui s'écrivent d'habitude en kana (事) ; les paires de particules souvent toutes deux correctes (は/が, に/へ, と/や…) ne sont jamais proposées ensemble ; les formes verbales qui conviendraient aussi (着て / 着たら / 着れば) sont écartées ; le 並べ替え ne garde que des morceaux dont l'ordre est imposé par la grammaire. Examen blanc : nombre de questions par type comme au vrai test (sans compréhension écrite), 1 minute par question, score par section, erreurs renvoyées dans les révisions.

Furigana des questions : comme au vrai test, les mots dont un kanji est au-dessus du niveau de la question (ou sans niveau) ont leur lecture au-dessus, examen compris ; le mot testé jamais. En entraînement, « Afficher la lecture » met aussi la lecture sur les autres mots (« Masquer la lecture » l'enlève, celles du test restent). Une fois répondu, chaque choix montre sa lecture en kana (dans la correction de l'examen aussi).

## Erreurs, annulation et révisions à la main

En session : **↶ Annuler ma réponse** (ou Ctrl+Z) oublie un mauvais clic ou une faute de frappe et remet la révision comme avant ; sur un nouvel exercice, il revient au précédent. **En fait je ne maîtrise pas** transforme une bonne réponse due à la chance en erreur (l'exercice revient en fin de session et demain). **Ne plus proposer** suspend un exercice ; **⚑ Signaler une erreur** retire pour de bon un exercice faux ou ambigu (il ne sera plus jamais généré). Dans Progrès → **Révisions** : tous les exercices avec leur prochaine révision, filtre par thème ou par texte, et pour ceux cochés : revoir aujourd'hui, suspendre, réactiver ou signaler ; « jamais vus » ajoute des exercices de la réserve à tes révisions.

## Langue (français / anglais)

L'app fonctionne en français ou en anglais : sélecteur en haut à droite (enregistré dans `data/settings.json`). L'interface, les titres et fiches des thèmes, le prof (consignes, situations de conversation, références) et les traductions des phrases suivent ce choix. Les nouveaux exercices sont générés avec un indice et une explication dans les deux langues ; les anciens n'ont que l'explication en français, masquée en anglais. Les traductions anglaises viennent de Tatoeba : `python build_bank.py` les garde désormais (à relancer une fois ; `--french-only` pour l'ancien comportement).

## Contrôle qualité (`review.py`)

```
python review.py revalidate             # revérifie la réserve avec les règles actuelles (fait aussi à chaque démarrage)
python review.py export --unseen > lot.json
python review.py reject 123 456 --reason "は et が possibles"
python review.py import relu.json       # retraits, corrections, nouvelles questions
```

Quand les règles s'améliorent, la réserve se nettoie au démarrage suivant : les exercices qui ne seraient plus générés sont retirés (et ne reviendront pas), les réponses acceptées sont mises à jour (に et へ tous deux justes avec 行く). Pour une relecture humaine, on exporte un lot, on le relit (toi, ou Claude), et on dépose le fichier relu dans `data/reviews/` : l'app l'applique au démarrage. Les thèmes de particules dont les deux réponses conviennent souvent ne gardent que les phrases où la grammaire tranche : は/が (が dans une subordonnée, 誰が, existence ; は avant un mot interrogatif), は/も (la traduction dit « aussi »), を/が (les deux acceptés avec たい et la forme potentielle), に/へ et と/や (les deux acceptés quand les deux sont justes).

## Démarrage en arrière-plan (`install_autostart.py`)

Ajoute un lanceur dans le dossier Démarrage de Windows : `pythonw server.py` tourne sans fenêtre ; ouvre http://localhost:8000. Au démarrage, le serveur synchronise Anki (une fois par jour), attend Ollama, puis complète la réserve et les questions JLPT (cases à cocher dans Progrès, ou `data/settings.json`). Journal : `data/server.log`. Pour l'enlever : `--uninstall`.

## Mesurer le LLM (`evaluate.py`)

```
python evaluate.py                    # 29 cas écrits à la main dans eval/particle_cases.json
python evaluate.py --model qwen3:8b --runs 3
```

Mesure à quelle fréquence la vérification garde les bons exercices et écarte les phrases ambiguës et les expressions figées. À relancer après chaque changement de prompt ou de modèle, et à noter dans `notes/log.md`.

Pour comparer deux modèles sur les mêmes exercices nouveaux (ce qu'ils gardent, leurs indices et explications, le temps), sans toucher à la réserve :

```
ollama pull qwen3:30b-a3b
python compare_models.py --models qwen3:14b,qwen3:30b-a3b     # → data/compare/<date>-….json
```

Le fichier se lit côte à côte (ou s'envoie pour relecture) : les bonnes réponses y sont, avec le verdict de chaque modèle à côté.

## Mises à jour de l'app (`updater.py`)

L'app Windows compare sa version avec la dernière release GitHub au démarrage. Réglage (écran d'accueil, ou Progrès → L'application) : **automatiques** (téléchargées en arrière-plan, installées à la fermeture de l'app), **me prévenir** (un bandeau avec un bouton « Mettre à jour » : l'app télécharge le nouvel exe, se ferme, le remplace et redémarre), ou **désactivées**. La progression reste dans %LOCALAPPDATA%\JapaneseCoach et n'est jamais touchée.

Pour publier une version : augmenter `VERSION` dans `updater.py`, `python build_exe.py`, puis une release GitHub avec le tag `v<VERSION>` et `JapaneseCoach.exe` en pièce jointe, sans la cocher en pre-release (GitHub exclut les pre-releases de « latest »).

## Banque d'exercices partagée (`bank_sync.py`)

Les exercices relus sont publiés dans un dépôt séparé, [Japanese-AI-Coach-bank](https://github.com/Aymeric-Dcn/Japanese-AI-Coach-bank). Chaque copie de l'app télécharge les nouveautés au démarrage (Progrès → Banque partagée → « Synchroniser maintenant ») : l'app fonctionne sans modèle local. Seul le contenu des exercices est partagé — jamais les réponses, la progression ni les données Anki.

```
python bank_sync.py pull                    # nouveaux exercices de la banque (aussi au démarrage)
python bank_sync.py contribute              # envoyer les exercices générés ici, pour relecture
python bank_sync.py import-inbox --repo ../Japanese-AI-Coach-bank   # mainteneur : contributions → réserve
python bank_sync.py publish --repo ../Japanese-AI-Coach-bank        # mainteneur : exercices relus → banque
```

Boucle de relecture : les exercices générés en local (ou reçus dans `inbox/` de la banque) sont marqués « non relus ». `python review.py export --unreviewed` donne un lot à relire ; le lot relu (retraits, corrections, `approve`) va dans `data/reviews/`, où l'app en marche l'applique ; `publish` écrit ensuite tous les exercices validés dans la banque. Réglages dans Progrès → Banque partagée : adresse de la banque (par défaut : le dépôt public), jeton GitHub (seulement pour un dépôt privé, ou pour envoyer des contributions vers `github:owner/repo`).

## Autres outils

- `generate_sheet.py` : cours + exercices entièrement écrits par le LLM (première version du projet, moins fiable).
- `anki_inspect.py` : liste les paquets Anki, le nombre de cartes et les champs.
