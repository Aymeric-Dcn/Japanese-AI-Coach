# Japanese Coach AI

*[English version](README.md)*

Un prof de japonais personnel qui tourne **en local** : des feuilles d'exercices à trous interactives construites à partir de vraies phrases, avec indices et explications écrits par un LLM local (via [Ollama](https://ollama.com)).

> Projet d'apprentissage : apprendre le japonais, et apprendre à configurer un LLM en même temps.

## Ce qui marche aujourd'hui

Deux façons de créer une feuille d'exercices :

| | `make_exercises.py` (recommandé) | `generate_sheet.py` |
| --- | --- | --- |
| Phrases | vraies phrases de [Tatoeba](https://tatoeba.org) | inventées par le LLM |
| Réponses et lectures | exactes (phrase d'origine + analyseur SudachiPy) | écrites par le LLM, erreurs possibles |
| Rôle du LLM | écarter les phrases ambiguës, écrire indices et explications | tout |
| Cours et vocabulaire | non | oui |

Les feuilles sont des pages HTML : on tape la réponse dans le trou au clavier japonais (compatible IME), on vérifie, on demande un indice, on voit l'explication et le score.

### Banque de vraies phrases

`build_bank.py` télécharge Tatoeba (une seule fois), garde les phrases japonaises traduites, les découpe avec SudachiPy (mots, catégories grammaticales, lectures) et les enregistre dans `data/bank.db`.

`make_exercises.py` y cherche les phrases qui contiennent exactement une des réponses visées, fait le trou lui-même, puis demande au LLM local si une autre réponse serait aussi correcte : si oui, la phrase est écartée. Chaque exercice affiche sa lecture en hiragana, sa traduction et un lien vers la phrase sur Tatoeba.

### Feuilles générées par le LLM

`generate_sheet.py` demande au modèle un cours (règles + exemples), du vocabulaire et des exercices. Le modèle écrit des phrases complètes en entourant la réponse de `【 】` ; c'est le script qui crée le trou, donc la réponse attendue est toujours exactement ce qui a été retiré. `--answers` impose une liste fermée de réponses (ex. `に,で`) et écarte les exercices hors sujet.

## Installation

Configuration testée : Windows, RTX 4070 Super (12 Go VRAM), 32 Go RAM.

1. **Ollama** : installer depuis [ollama.com/download](https://ollama.com/download).
2. **Un modèle** :
   ```
   ollama pull qwen3:14b
   ```
3. **Python 3.9+** : [python.org](https://www.python.org/downloads/) (cocher *Add python.exe to PATH*), puis les dépendances :
   ```
   pip install -r requirements.txt
   ```
4. **Clavier japonais** (pour remplir les exercices) : Paramètres → Heure et langue → Langue et région → ajouter *Japonais*. Basculer avec `Windows + Espace`.

## Utilisation

### Exercices à partir de vraies phrases

```
python build_bank.py        # une seule fois (quelques minutes)
python make_exercises.py --targets "に,で" --pos 格助詞 --title "Les particules に et で"
python make_exercises.py --targets "は,が" --pos 助詞 --max-words 8
```

| Option | Rôle | Défaut |
| --- | --- | --- |
| `--targets` | les réponses à faire retrouver | — |
| `--pos` | catégorie grammaticale exigée : `格助詞` (particule de cas), `助詞` (toute particule)… Évite par ex. le で de 読んで | aucune |
| `--count` | nombre d'exercices | `10` |
| `--min-words` / `--max-words` | longueur des phrases (≈ difficulté) | `3` / `12` |
| `--any-context` | particules : accepter aussi すぐに, 親切に, には, でも… (par défaut, seuls les cas simples « nom + particule » sont gardés) | — |
| `--no-llm` | pas de vérification ni d'explication (instantané) | — |
| `--english` | accepter les phrases traduites seulement en anglais (lancer aussi `build_bank.py --english`) | — |
| `--level` | niveau de l'élève, pour les explications | `N5` |
| `--model` | modèle Ollama | `qwen3:14b` |
| `--seed` | retrouver la même sélection de phrases | aléatoire |

### Exercices inventés par le LLM

```
python generate_sheet.py --topic "les particules に et で" --level N5 --answers "に,で"
python generate_sheet.py --topic "la forme en て" --level N5 --count 12
python generate_sheet.py --demo        # feuille d'exemple, sans Ollama
```

| Option | Rôle | Défaut |
| --- | --- | --- |
| `--topic` | le point de grammaire à travailler | — |
| `--level` | N5, N4… ou une description libre | `N5` |
| `--count` | nombre d'exercices | `10` |
| `--answers` | liste fermée des réponses possibles | aucune |
| `--model` | modèle Ollama | `qwen3:14b` |
| `--temperature` | 0 = strict, 1 = varié | `0.7` |

Les feuilles sont enregistrées dans `sheets/` (HTML + JSON) et ouvertes dans le navigateur.

## Organisation du projet

```
build_bank.py       Tatoeba → SudachiPy → data/bank.db
make_exercises.py   feuille d'exercices à partir de la banque (+ vérification et explications par le LLM)
generate_sheet.py   feuille d'exercices entièrement générée par le LLM
sheet.py            fonctions communes et page HTML interactive
notes/log.md        journal des tests (modèles, prompts, résultats), en anglais
```

## Feuille de route

- [x] Feuilles d'exercices à trous générées par un LLM local
- [x] **Banque de phrases** Tatoeba découpées par SudachiPy, trous exacts, le LLM ne fait qu'écarter les phrases ambiguës et expliquer
- [ ] Exercices sur les formes verbales (forme en て, passé, négatif…) à partir de la banque
- [ ] Vérification du vocabulaire avec [JMdict](https://www.edrdg.org/jmdict/j_jmdict.html)
- [ ] **Synchronisation Anki** (AnkiConnect) : choisir des phrases dont je connais déjà le vocabulaire
- [ ] Suivi des erreurs et **répétition espacée**
- [ ] **Chat** avec le prof (explications, correction de phrases libres)
- [ ] Jeu de tests pour **mesurer** la fiabilité des modèles et des prompts
- [ ] Interface d'application unifiée

## Sources de données et droits

Le dépôt ne contient que du code, des prompts et de la documentation. Les données téléchargées ou personnelles (`data/`, `sources/`, bases SQLite, feuilles générées) sont exclues par le `.gitignore`. Aucun contenu tiré de manuels sous droits ne doit être publié ici.

Sources libres utilisées ou prévues : Tatoeba (CC BY 2.0 FR), JMdict / KANJIDIC (CC BY-SA 4.0, EDRDG), guide de grammaire de Tae Kim (CC BY-NC-SA 3.0).
