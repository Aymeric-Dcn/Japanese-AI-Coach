"""
The chat tutor: builds what the local LLM receives (system prompt for the chosen mode, student
context, analysis of the student's Japanese sentences, reliable references from knowledge.py)
and keeps the conversation in data/coach.db.

Modes:
  prof          questions, explanations, corrections (default)
  conversation  a conversation in simple Japanese, with a translation and gentle corrections
  quiz          the tutor asks questions on the student's weak points, one at a time
"""

import json
import re
from pathlib import Path

import knowledge
import store

KNOWN_PATH = Path("data") / "known.json"
JAPANESE = re.compile(r"[぀-ヿ㐀-鿿]")

SYSTEM_PROMPT = """Tu es « Sensei », le professeur de japonais personnel d'un élève francophone.
Tu réponds en français, de façon claire, chaleureuse et concise (pas d'emoji). Tu es rigoureux : si tu
n'es pas sûr d'une règle ou d'un usage, dis-le plutôt que d'inventer.

Règles :
- Quand tu écris du japonais, ajoute la lecture en hiragana entre parenthèses après les mots en kanji
  qui dépassent le niveau N5/N4, puis la traduction.
- Quand l'élève te demande de corriger une phrase : dis d'abord si elle est correcte, donne la version
  corrigée, puis explique chaque correction (particule, conjugaison, vocabulaire, naturel).
  Une « analyse morphologique » automatique de sa phrase peut t'être fournie : elle est fiable pour
  le découpage et les lectures, mais ne dit pas si la phrase est correcte.
- Donne peu d'exemples, courts, avec du vocabulaire simple, et seulement des phrases dont tu es certain
  qu'elles sont correctes et naturelles. Relis chaque exemple japonais avant de l'écrire.
- Reste sur la question posée : n'ajoute pas de listes de règles voisines que l'élève n'a pas demandées.
- Utilise des listes et du **gras** avec parcimonie ; pas de tableaux.

{student}"""

CONVERSATION_PROMPT = """Tu es « Sensei », et tu fais la conversation en japonais avec un élève francophone de niveau {level}.
{scenario}
Règles :
- Réponds d'abord en japonais simple et naturel (niveau {level}, 1 à 3 phrases courtes), en style poli (です / ます).
  Termine souvent par une question pour faire continuer la conversation.
- Puis, sur une nouvelle ligne commençant par « → », la traduction française de ta réplique.
- Si le dernier message de l'élève contient des fautes, ajoute ensuite une ligne « Correction : » avec sa phrase
  corrigée et une explication très courte en français. S'il n'y a pas de faute, n'ajoute rien.
- Si l'élève écrit en français, aide-le à dire la même chose en japonais.
- Pas d'emoji, pas de romaji.

{student}"""

QUIZ_PROMPT = """Tu es « Sensei », professeur de japonais d'un élève francophone de niveau {level}, et tu l'interroges.
Règles :
- Pose UNE seule question à la fois, courte, sur ses points faibles ci-dessous (particules, conjugaisons,
  vocabulaire) : phrase à trou, traduction courte, ou « quelle est la différence entre… ».
- Quand il répond : dis si c'est juste, corrige et explique en une ou deux phrases, puis pose la question suivante.
- Varie les questions, reste à son niveau, en français (le japonais seulement pour les phrases).
- Pas d'emoji.

{student}"""

SCENARIOS = {
    "free": "Sujet libre : commence par saluer l'élève et lui poser une question simple sur sa journée.",
    "intro": "Situation : vous faites connaissance (se présenter, métier, loisirs, pourquoi il apprend le japonais).",
    "restaurant": "Situation : tu es serveur dans un restaurant au Japon, l'élève est client.",
    "konbini": "Situation : tu es employé d'un konbini, l'élève fait ses courses.",
    "directions": "Situation : l'élève est perdu dans Tokyo et te demande son chemin ; tu es un passant.",
    "hotel": "Situation : tu es réceptionniste d'un hôtel, l'élève arrive pour s'enregistrer.",
    "weekend": "Situation : vous parlez de vos projets pour le week-end.",
}

def student_context(db) -> str:
    """What the tutor knows about the student: level, vocabulary size, recent mistakes."""
    lines = ["Ce que tu sais de l'élève :"]
    if KNOWN_PATH.exists():
        known = json.loads(KNOWN_PATH.read_text(encoding="utf-8"))
        lines.append(f"- Il connaît environ {len(known.get('words', [])) // 2} mots et {len(known.get('kanji', []))} "
                     f"kanji dans Anki (niveau JLPT N5 terminé, N4 en cours).")
    rows = db.execute("""
        SELECT e.topic, e.data, r.answer FROM reviews r JOIN exercises e ON e.id = r.exercise_id
        WHERE r.correct = 0 ORDER BY r.id DESC LIMIT 8""").fetchall()
    if rows:
        lines.append("- Ses dernières erreurs dans les exercices :")
        for row in rows:
            ex = json.loads(row["data"])
            given = row["answer"] or "(réponse affichée)"
            lines.append(f"  · {row['topic']} : {ex.get('full_sentence', '')} — attendu « {ex['answers'][0]} », "
                         f"il a répondu « {given} »")
    return "\n".join(lines) if len(lines) > 1 else ""


_analyzer = None


def tokenize(text: str) -> list:
    """SudachiPy tokens of every Japanese line of the message (empty if SudachiPy is missing)."""
    global _analyzer
    if not JAPANESE.search(text):
        return []
    try:
        import build_bank
        if _analyzer is None:
            _analyzer = build_bank.make_analyzer()
        tokens = []
        for line in text.splitlines():
            if JAPANESE.search(line):
                tokens += build_bank.analyze(_analyzer, line)
        return tokens
    except (SystemExit, Exception):
        return []


def analyze(text: str, tokens: list = None) -> str:
    """Morphological analysis of the Japanese in the message, as text for the LLM."""
    tokens = tokenize(text) if tokens is None else tokens
    return " | ".join(f"{t[0]} [{t[1]}/{t[2]}, lecture {t[3]}, forme {t[4]}]" for t in tokens if t[1] != "空白")


def reading(word: str) -> str:
    """Hiragana reading of a word (empty if SudachiPy is missing or the word is already in kana)."""
    global _analyzer
    try:
        import build_bank
        if _analyzer is None:
            _analyzer = build_bank.make_analyzer()
        r = build_bank.reading(_analyzer, word)
        return "" if r == word else r
    except (SystemExit, Exception):
        return ""


def exercise_context(ex: dict) -> str:
    """Text added to the student's question when asked from an exercise (« Demander au prof »)."""
    lines = ["[Contexte : l'élève pose une question sur cet exercice]",
             f"Phrase : {ex.get('full_sentence', '')}",
             f"Exercice : {ex.get('sentence', '')}" + (f" (verbe : {ex['cue']})" if ex.get("cue") else ""),
             f"Réponse attendue : {', '.join(ex.get('answers', []))}"]
    if ex.get("choices"):
        lines.append(f"Choix proposés (QCM) : {' / '.join(ex['choices'])}")
    if ex.get("topic"):
        lines.append(f"Thème : {ex['topic']}")
    if ex.get("given"):
        lines.append(f"Réponse de l'élève : {ex['given']}")
    if ex.get("translation"):
        lines.append(f"Traduction : {ex['translation']}")
    if ex.get("explanation"):
        lines.append(f"Explication déjà donnée : {ex['explanation']}")
    return "\n".join(lines)


def student_level() -> str:
    try:
        settings = json.loads((Path("data") / "settings.json").read_text(encoding="utf-8"))
        return settings.get("jlpt_level", "N4")
    except (OSError, ValueError):
        return "N4"


def weak_points(db) -> str:
    rows = db.execute("""
        SELECT e.topic, COUNT(*) AS n, SUM(r.correct) AS ok FROM reviews r JOIN exercises e ON e.id = r.exercise_id
        GROUP BY e.topic HAVING n >= 3 ORDER BY 1.0 * ok / n LIMIT 4""").fetchall()
    if not rows:
        return "- Pas encore assez de résultats : interroge-le sur les particules は/が, に/で et la forme en て."
    return "- Ses thèmes les plus difficiles : " + ", ".join(
        f"{r['topic']} ({round(100 * r['ok'] / r['n'])} % de réussite)" for r in rows)


def build_messages(db, conversation: str, message: str, exercise: dict = None,
                   mode: str = "prof", scenario: str = "free") -> tuple:
    """(messages for the LLM, labels of the references used)."""
    level = student_level()
    student = student_context(db)
    if mode == "conversation":
        system = CONVERSATION_PROMPT.format(level=level, scenario=SCENARIOS.get(scenario, SCENARIOS["free"]),
                                            student=student)
    elif mode == "quiz":
        system = QUIZ_PROMPT.format(level=level, student=student + "\n" + weak_points(db))
    else:
        system = SYSTEM_PROMPT.format(student=student)
    history = store.conversation(db, conversation, limit=20)
    content = message
    if exercise:
        content = exercise_context(exercise) + "\n\nQuestion de l'élève : " + message
    tokens = tokenize(message)
    if tokens and mode != "quiz":
        content += "\n\n[Analyse morphologique automatique du japonais de l'élève]\n" + analyze(message, tokens)
    labels = []
    if mode == "prof":
        refs, labels = knowledge.references(message, tokens, exercise)
        if refs:
            content += "\n\n" + refs
    return [{"role": "system", "content": system}] + history + [{"role": "user", "content": content}], labels
