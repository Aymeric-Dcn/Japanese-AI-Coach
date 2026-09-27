# Journal des tests

## 2026-09-27 — Premier test : particules に et で (N5)

Matériel : RTX 4070 Super 12 Go, 32 Go RAM, Ollama.

**gemma3:12b — écarté**
- Explications fausses : pour 学校で勉強します et 家で会います, il affirme qu'on utilise に.
- Les trous cachent le nom au lieu de la particule : questions impossibles.
- Plusieurs exercices sans réponse exploitable.

**qwen3:14b — retenu**
- 7/10 du premier coup, globalement correct.
- Erreurs : exemple 本を読んでいる rangé sous la règle de で ; explication « で indique l'action en cours » fausse ; un exercice hors sujet (を) ; lectures en romaji au lieu de hiragana.
- Même problème de trous mal placés que Gemma sur certains exercices.

**Correctifs apportés au script**
- Le modèle entoure la réponse de `【 】` dans une phrase complète ; le script crée le trou lui-même.
- Option `--reponses` : liste fermée de réponses, les exercices hors liste sont écartés.
- Prompt plus strict (exemple de format, hiragana obligatoire, exemples cohérents avec leur règle).
- Génération de quelques exercices en plus et nouvel essai si besoin, pour atteindre le nombre demandé.

**Conclusion** : un modèle local invente des phrases *et* leurs réponses avec des erreurs. Piste retenue : banque d'exercices à partir de vraies phrases (Tatoeba) + analyseur morphologique, le LLM servant seulement à annoter et expliquer.
