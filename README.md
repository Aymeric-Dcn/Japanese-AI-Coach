# Japanese Coach AI

Un prof de japonais personnel qui tourne **en local** : un LLM (via [Ollama](https://ollama.com)) génère des feuilles de cours et des exercices à trous interactifs, avec correction et explications en français.

> Projet d'apprentissage : apprendre le japonais, et apprendre à configurer un LLM en même temps.

## Ce qui marche aujourd'hui

Deux façons de créer une feuille d'exercices :

| | `creer_exercices.py` (recommandé) | `generer_feuille.py` |
| --- | --- | --- |
| Phrases | vraies phrases de [Tatoeba](https://tatoeba.org) | inventées par le LLM |
| Réponses et lectures | exactes (phrase d'origine + analyseur SudachiPy) | écrites par le LLM, erreurs possibles |
| Rôle du LLM | écarter les phrases ambiguës, écrire indices et explications | tout |
| Cours et vocabulaire | non | oui |

### Banque de vraies phrases

`construire_banque.py` télécharge Tatoeba (une seule fois), garde les phrases japonaises traduites, les découpe avec SudachiPy (mots, catégories grammaticales, lectures) et les enregistre dans `data/banque.db`.

`creer_exercices.py` y cherche les phrases qui contiennent exactement une des réponses visées, fait le trou lui-même, puis demande au LLM local si une autre réponse serait aussi correcte : si oui, la phrase est écartée. Chaque exercice affiche sa lecture en hiragana, sa traduction et un lien vers la phrase sur Tatoeba.

### Feuilles générées par le LLM

`generer_feuille.py` produit une page HTML avec :

- un **cours** (règles + exemples avec lecture en hiragana et traduction) ;
- une liste de **vocabulaire** ;
- des **exercices à trous** à remplir au clavier (IME japonais compatible), avec indice, vérification, explication et score.

Le modèle écrit des phrases complètes en entourant la réponse de `【 】` ; c'est le script qui crée le trou, donc la réponse attendue est toujours exactement ce qui a été retiré. L'option `--reponses` impose une liste fermée de réponses (ex. `に,で`) et écarte tout exercice hors sujet.

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
python construire_banque.py        # une seule fois (quelques minutes)
python creer_exercices.py --cibles "に,で" --pos 格助詞 --titre "Les particules に et で"
python creer_exercices.py --cibles "は,が" --pos 助詞 --max-mots 8
```

| Option | Rôle | Défaut |
| --- | --- | --- |
| `--cibles` | les réponses à faire retrouver | — |
| `--pos` | catégorie grammaticale exigée : `格助詞` (particule de cas), `助詞` (toute particule)… Évite par ex. le で de 読んで | aucune |
| `--nb` | nombre d'exercices | `10` |
| `--min-mots` / `--max-mots` | longueur des phrases (≈ difficulté) | `3` / `12` |
| `--sans-llm` | pas de vérification ni d'explication (instantané) | — |
| `--anglais` | accepter les phrases traduites seulement en anglais (lancer aussi `construire_banque.py --anglais`) | — |
| `--graine` | retrouver la même sélection de phrases | aléatoire |

### Exercices inventés par le LLM

```
python generer_feuille.py --theme "les particules に et で" --niveau N5 --reponses "に,で"
python generer_feuille.py --theme "la forme en て" --niveau N5 --nb 12
python generer_feuille.py --demo        # feuille d'exemple, sans Ollama
```

| Option | Rôle | Défaut |
| --- | --- | --- |
| `--theme` | le point de grammaire à travailler | — |
| `--niveau` | N5, N4… ou une description libre | `N5` |
| `--nb` | nombre d'exercices | `10` |
| `--reponses` | liste fermée des réponses possibles | aucune |
| `--modele` | modèle Ollama | `qwen3:14b` |
| `--temperature` | 0 = strict, 1 = varié | `0.7` |

Les feuilles sont enregistrées dans `feuilles/` (HTML + JSON) et ouvertes dans le navigateur.

## Feuille de route

- [x] Génération de feuilles d'exercices à trous par un LLM local
- [x] **Banque de phrases** Tatoeba découpées par SudachiPy, exercices à trous exacts, le LLM ne fait qu'écarter les phrases ambiguës et expliquer
- [ ] Exercices sur les formes verbales (forme en て, passé, négatif…) à partir de la banque
- [ ] Vérification du vocabulaire avec [JMdict](https://www.edrdg.org/jmdict/j_jmdict.html)
- [ ] **Synchronisation Anki** (AnkiConnect) : choisir des phrases dont je connais déjà tout le vocabulaire sauf un mot
- [ ] Suivi des erreurs et **répétition espacée**
- [ ] **Chat** avec le prof (explications, correction de phrases libres)
- [ ] Jeu de tests pour **mesurer** la fiabilité des modèles et des prompts
- [ ] Interface d'application unifiée

## Journal des tests

Voir [`notes/journal.md`](notes/journal.md).

## Sources de données et droits

Le dépôt ne contient que du code, des prompts et de la documentation. Les données téléchargées ou personnelles (`data/`, `sources/`, bases SQLite, feuilles générées) sont exclues par le `.gitignore`. Aucun contenu tiré de manuels sous droits ne doit être publié ici.

Sources libres prévues : Tatoeba (CC BY 2.0 FR), JMdict / KANJIDIC (CC BY-SA 4.0, EDRDG), guide de grammaire de Tae Kim (CC BY-NC-SA 3.0).
