# Japanese Coach AI

Un prof de japonais personnel qui tourne **en local** : un LLM (via [Ollama](https://ollama.com)) génère des feuilles de cours et des exercices à trous interactifs, avec correction et explications en français.

> Projet d'apprentissage : apprendre le japonais, et apprendre à configurer un LLM en même temps.

## Ce qui marche aujourd'hui

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
3. **Python 3.9+** : [python.org](https://www.python.org/downloads/) (cocher *Add python.exe to PATH*). Aucune bibliothèque à installer pour l'instant.
4. **Clavier japonais** (pour remplir les exercices) : Paramètres → Heure et langue → Langue et région → ajouter *Japonais*. Basculer avec `Windows + Espace`.

## Utilisation

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
- [ ] **Banque d'exercices** construite à partir de vraies phrases ([Tatoeba](https://tatoeba.org)), découpées par un analyseur morphologique (SudachiPy) : trous et lectures exacts, le LLM ne fait qu'écrire indices et explications
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
