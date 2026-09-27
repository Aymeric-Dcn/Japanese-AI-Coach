"""
The chat tutor: builds what the local LLM receives (system prompt, student context,
analysis of the student's Japanese sentences) and keeps the conversation in data/coach.db.
"""

import json
import re
from pathlib import Path

import store

KNOWN_PATH = Path("data") / "known.json"
JAPANESE = re.compile(r"[぀-ヿ㐀-鿿]")

SYSTEM_PROMPT = """Tu es « Sensei », le professeur de japonais personnel d'un élève francophone.
Tu réponds en français, de façon claire, chaleureuse et concise. Tu es rigoureux : si tu n'es pas sûr
d'une règle ou d'un usage, dis-le plutôt que d'inventer.

Règles :
- Quand tu écris du japonais, ajoute la lecture en hiragana entre parenthèses après les mots en kanji
  qui dépassent le niveau N5/N4, puis la traduction.
- Quand l'élève te demande de corriger une phrase : dis d'abord si elle est correcte, donne la version
  corrigée, puis explique chaque correction (particule, conjugaison, vocabulaire, naturel).
  Une « analyse morphologique » automatique de sa phrase peut t'être fournie : elle est fiable pour
  le découpage et les lectures, mais ne dit pas si la phrase est correcte.
- Donne des exemples courts, avec du vocabulaire simple.
- Utilise des listes et du **gras** avec parcimonie ; pas de tableaux.

{student}"""


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


def analyze(text: str) -> str:
    """Morphological analysis of the Japanese in the message (empty if SudachiPy is missing)."""
    global _analyzer
    if not JAPANESE.search(text):
        return ""
    try:
        if _analyzer is None:
            import build_bank
            _analyzer = build_bank.make_analyzer()
        parts = []
        for line in text.splitlines():
            if JAPANESE.search(line):
                tokens = build_bank.analyze(_analyzer, line)
                parts.append(" | ".join(f"{t[0]} [{t[1]}/{t[2]}, lecture {t[3]}, forme {t[4]}]"
                                        for t in tokens if t[1] not in ("空白",)))
        return "\n".join(parts)
    except (SystemExit, Exception):
        return ""


def exercise_context(ex: dict) -> str:
    """Text added to the student's question when asked from an exercise (« Demander au prof »)."""
    lines = ["[Contexte : l'élève pose une question sur cet exercice]",
             f"Phrase : {ex.get('full_sentence', '')}",
             f"Exercice : {ex.get('sentence', '')}" + (f" (verbe : {ex['cue']})" if ex.get("cue") else ""),
             f"Réponse attendue : {', '.join(ex.get('answers', []))}"]
    if ex.get("given"):
        lines.append(f"Réponse de l'élève : {ex['given']}")
    if ex.get("translation"):
        lines.append(f"Traduction : {ex['translation']}")
    if ex.get("explanation"):
        lines.append(f"Explication déjà donnée : {ex['explanation']}")
    return "\n".join(lines)


def build_messages(db, conversation: str, message: str, exercise: dict = None) -> list:
    """Full message list for the LLM: system prompt + history + the new message (with context)."""
    system = SYSTEM_PROMPT.format(student=student_context(db))
    history = store.conversation(db, conversation, limit=20)
    content = message
    if exercise:
        content = exercise_context(exercise) + "\n\nQuestion de l'élève : " + message
    analysis = analyze(message)
    if analysis:
        content += "\n\n[Analyse morphologique automatique du japonais de l'élève]\n" + analysis
    return [{"role": "system", "content": system}] + history + [{"role": "user", "content": content}]
