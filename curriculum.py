"""
The study programme: grammar topics in teaching order, from JLPT N5 to N4.

Each topic is an exercise recipe for make_exercises.py:
  - particles:    "targets" (the possible answers) + "pos" (required part of speech);
  - conjugations: "form" (see make_exercises.FORMS).

Progression (see store.topic_states):
  - a topic is "passed" when it is mastered (≥ 80 % right over its last 20 answers, at least 10 answers),
    fast-tracked (5 answers or more, all right), or marked « Je maîtrise déjà » in the app;
  - the daily session brings new exercises from the first MAX_CURRENT topics not passed yet;
    the following ones stay locked until one of them is passed. Reviews of every topic keep coming back.
"""

MAX_CURRENT = 2
MASTERY_WINDOW = 20      # answers considered to measure a topic
MASTERY_MIN = 10         # answers needed before a topic can be mastered
MASTERY_RATE = 0.8
FAST_TRACK_MIN = 5       # this many answers, all right → passed straight away

TOPICS = [
    # ---------------- N5 ----------------
    {"id": "masu", "level": "N5", "title": "Forme polie en ます", "form": "masu"},
    {"id": "wa-ga", "level": "N5", "title": "Particules は / が", "targets": "は,が", "pos": "係助詞,格助詞"},
    {"id": "wo-ga", "level": "N5", "title": "Particules を / が", "targets": "を,が", "pos": "格助詞"},
    {"id": "ni-de", "level": "N5", "title": "Particules に / で", "targets": "に,で", "pos": "格助詞"},
    {"id": "negative", "level": "N5", "title": "Négatif en ない", "form": "negative"},
    {"id": "ni-e", "level": "N5", "title": "Particules に / へ", "targets": "に,へ", "pos": "格助詞"},
    {"id": "past", "level": "N5", "title": "Passé en た", "form": "past"},
    {"id": "wa-mo", "level": "N5", "title": "Particules は / も", "targets": "は,も", "pos": "係助詞"},
    {"id": "to-ya", "level": "N5", "title": "Particules と / や", "targets": "と,や", "pos": "格助詞,副助詞"},
    {"id": "te-form", "level": "N5", "title": "Forme en て", "form": "te"},
    {"id": "kara-made", "level": "N5", "title": "Particules から / まで", "targets": "から,まで", "pos": "格助詞,副助詞"},
    {"id": "tai", "level": "N5", "title": "Envie : forme en たい", "form": "tai"},
    # ---------------- N4 ----------------
    {"id": "volitional", "level": "N4", "title": "Volitif en う / よう", "form": "volitional"},
    {"id": "nagara", "level": "N4", "title": "Simultanéité : ながら", "form": "nagara"},
    {"id": "ba", "level": "N4", "title": "Conditionnel en ば", "form": "ba"},
    {"id": "tara", "level": "N4", "title": "Conditionnel en たら", "form": "tara"},
    {"id": "noni-node", "level": "N4", "title": "のに / ので", "targets": "のに,ので", "pos": "接続助詞"},
    {"id": "causative", "level": "N4", "title": "Causatif en せる / させる", "form": "causative"},
]

BY_ID = {t["id"]: t for t in TOPICS}
BY_TITLE = {t["title"]: t for t in TOPICS}
ORDER = {t["title"]: i for i, t in enumerate(TOPICS)}


def kind(topic: dict) -> str:
    return "conjugation" if "form" in topic else "particle"


def is_particle_topic(title: str) -> bool:
    t = BY_TITLE.get(title)
    return bool(t) and "targets" in t
