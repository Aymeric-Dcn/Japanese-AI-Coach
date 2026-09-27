"""
Progress database (data/coach.db): the exercise reserve, every answer, and the review schedule.

Tables:
  exercises  — one row per exercise, its content stored as JSON (same shape as in sheets)
  reviews    — every answer (first attempt only)
  schedule   — when each exercise already seen comes back (spaced repetition)
  messages   — chat history with the tutor
  topic_flags — topics marked « Je maîtrise déjà » in the app
"""

import datetime
import json
import random
import sqlite3
from pathlib import Path

import curriculum
import srs

DB_PATH = Path("data") / "coach.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS exercises (
    id INTEGER PRIMARY KEY,
    topic TEXT NOT NULL,          -- shown in the app, e.g. « Particules に / で »
    kind TEXT NOT NULL,           -- "particle" or "conjugation"
    source_key TEXT UNIQUE,       -- e.g. "tatoeba:12345:で", avoids adding the same exercise twice
    data TEXT NOT NULL,           -- exercise JSON: sentence, answers, hint, explanation…
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    exercise_id INTEGER NOT NULL REFERENCES exercises(id),
    reviewed_at TEXT NOT NULL,    -- ISO date-time
    day TEXT NOT NULL,            -- ISO date, for daily stats
    correct INTEGER NOT NULL,     -- 1 if right on the first attempt
    answer TEXT
);
CREATE TABLE IF NOT EXISTS schedule (
    exercise_id INTEGER PRIMARY KEY REFERENCES exercises(id),
    due TEXT NOT NULL,            -- ISO date of the next review
    interval INTEGER NOT NULL,
    streak INTEGER NOT NULL,
    lapses INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    conversation TEXT NOT NULL,
    role TEXT NOT NULL,           -- "user" or "assistant"
    content TEXT NOT NULL,
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topic_flags (
    topic TEXT PRIMARY KEY,
    known INTEGER NOT NULL,       -- 1 = « Je maîtrise déjà »: the topic counts as passed
    updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_day ON reviews(day);
CREATE INDEX IF NOT EXISTS idx_schedule_due ON schedule(due);
"""


def connect(path: Path = None) -> sqlite3.Connection:
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def today() -> datetime.date:
    return datetime.date.today()


# ---------------------------------------------------------------------------
# Exercise reserve
# ---------------------------------------------------------------------------

def existing_keys(db) -> set:
    return {r[0] for r in db.execute("SELECT source_key FROM exercises WHERE source_key IS NOT NULL")}


def add_exercise(db, topic: str, kind: str, data: dict, source_key: str = None) -> bool:
    """Adds one exercise; returns False if it was already in the reserve."""
    cur = db.execute(
        "INSERT OR IGNORE INTO exercises (topic, kind, source_key, data, created) VALUES (?, ?, ?, ?, ?)",
        (topic, kind, source_key, json.dumps(data, ensure_ascii=False), datetime.datetime.now().isoformat()),
    )
    db.commit()
    return cur.rowcount == 1


def _exercise(row) -> dict:
    ex = json.loads(row["data"])
    ex.update({"id": row["id"], "topic": row["topic"], "kind": row["kind"]})
    return ex


def topics(db) -> list:
    """[{topic, total, unseen}] for every topic of the reserve."""
    rows = db.execute("""
        SELECT e.topic, COUNT(*) AS total, SUM(s.exercise_id IS NULL) AS unseen
        FROM exercises e LEFT JOIN schedule s ON s.exercise_id = e.id
        GROUP BY e.topic ORDER BY e.topic""")
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Daily session
# ---------------------------------------------------------------------------

def session(db, day: datetime.date = None, new_limit: int = 10, due_limit: int = 50,
            topics: list = None, seed=None, topic: str = None) -> list:
    """Exercises due today (oldest first), then up to `new_limit` never-seen exercises mixed across topics.
    `topics`: only these topics (None = all)."""
    day = (day or today()).isoformat()
    if topic:
        topics = [topic]
    where_topic, topic_params = "", []
    if topics is not None:
        if not topics:
            return []
        where_topic = f" AND e.topic IN ({','.join('?' * len(topics))})"
        topic_params = list(topics)
    due = db.execute(f"""
        SELECT e.* FROM exercises e JOIN schedule s ON s.exercise_id = e.id
        WHERE s.due <= ?{where_topic} ORDER BY s.due, e.id LIMIT ?""", [day] + topic_params + [due_limit]).fetchall()
    unseen = db.execute(f"""
        SELECT e.* FROM exercises e LEFT JOIN schedule s ON s.exercise_id = e.id
        WHERE s.exercise_id IS NULL{where_topic}""", topic_params).fetchall()

    # Mix new exercises across topics: shuffle each topic, then take them in turn.
    rng = random.Random(seed)
    by_topic = {}
    for row in unseen:
        by_topic.setdefault(row["topic"], []).append(row)
    pools = [rng.sample(v, len(v)) for v in by_topic.values()]
    rng.shuffle(pools)
    new = []
    while len(new) < new_limit and any(pools):
        for pool in pools:
            if pool and len(new) < new_limit:
                new.append(pool.pop())

    items = [dict(_exercise(r), status="review") for r in due]
    items += [dict(_exercise(r), status="new") for r in new]
    return items


def daily_session(db, day: datetime.date = None, new_limit: int = 10, seed=None) -> dict:
    """The programme's session: every review due, new exercises from the current topics only."""
    states = topic_states(db)
    current = [t["title"] for t in states if t["state"] == "current"]
    due = session(db, day, new_limit=0, seed=seed)
    new = [x for x in session(db, day, new_limit=new_limit, topics=current, seed=seed) if x["status"] == "new"]
    return {"items": due + new, "current": current,
            "empty_current": [t["title"] for t in states if t["state"] == "current" and not t["unseen"]]}


# ---------------------------------------------------------------------------
# Programme progression
# ---------------------------------------------------------------------------

def topic_performance(db, title: str) -> dict:
    """First-attempt results of the topic's last answers."""
    rows = db.execute("""
        SELECT r.correct FROM reviews r JOIN exercises e ON e.id = r.exercise_id
        WHERE e.topic = ? ORDER BY r.id DESC LIMIT ?""", (title, curriculum.MASTERY_WINDOW)).fetchall()
    answers = len(rows)
    right = sum(r[0] for r in rows)
    return {"answers": answers, "right": right, "rate": right / answers if answers else None}


def is_passed(perf: dict, flagged: bool) -> tuple:
    if flagged:
        return True, "marqué comme maîtrisé"
    n, rate = perf["answers"], perf["rate"]
    if n >= curriculum.MASTERY_MIN and rate >= curriculum.MASTERY_RATE:
        return True, f"maîtrisé ({round(100 * rate)} % sur {n} réponses)"
    if n >= curriculum.FAST_TRACK_MIN and rate == 1:
        return True, f"validé d'office ({n} réponses justes)"
    return False, ""


def topic_states(db) -> list:
    """Every programme topic with its state: passed, current (new exercises come from here) or locked.
    Reserve topics that are not in the programme are listed at the end with the state « custom »."""
    flags = {r["topic"]: bool(r["known"]) for r in db.execute("SELECT topic, known FROM topic_flags")}
    reserve = {t["topic"]: t for t in topics(db)}
    states, current = [], 0
    for t in curriculum.TOPICS:
        perf = topic_performance(db, t["title"])
        passed, why = is_passed(perf, flags.get(t["title"], False))
        if passed:
            state = "passed"
        elif current < curriculum.MAX_CURRENT:
            state, current = "current", current + 1
        else:
            state = "locked"
        res = reserve.get(t["title"], {"total": 0, "unseen": 0})
        states.append({"id": t["id"], "title": t["title"], "level": t["level"], "kind": curriculum.kind(t),
                       "state": state, "why": why, "flagged": flags.get(t["title"], False),
                       "total": res["total"], "unseen": res["unseen"], **perf})
    for title, res in reserve.items():
        if title not in curriculum.BY_TITLE:
            perf = topic_performance(db, title)
            states.append({"id": None, "title": title, "level": "", "kind": "", "state": "custom", "why": "",
                           "flagged": False, "total": res["total"], "unseen": res["unseen"], **perf})
    return states


def set_topic_known(db, title: str, known: bool) -> None:
    db.execute("""INSERT INTO topic_flags (topic, known, updated) VALUES (?, ?, ?)
                  ON CONFLICT(topic) DO UPDATE SET known = excluded.known, updated = excluded.updated""",
               (title, int(known), datetime.datetime.now().isoformat(timespec="seconds")))
    db.commit()


def record_answer(db, exercise_id: int, correct: bool, answer: str = "", day: datetime.date = None) -> dict:
    """Saves the first attempt of an exercise and schedules its next review."""
    day = day or today()
    if not db.execute("SELECT 1 FROM exercises WHERE id = ?", (exercise_id,)).fetchone():
        raise KeyError(f"unknown exercise {exercise_id}")
    db.execute("INSERT INTO reviews (exercise_id, reviewed_at, day, correct, answer) VALUES (?, ?, ?, ?, ?)",
               (exercise_id, datetime.datetime.now().isoformat(timespec="seconds"), day.isoformat(),
                int(bool(correct)), answer))
    row = db.execute("SELECT interval, streak, lapses FROM schedule WHERE exercise_id = ?", (exercise_id,)).fetchone()
    interval, streak, lapses = (row["interval"], row["streak"], row["lapses"]) if row else (0, 0, 0)
    interval, streak, lapses = srs.next_state(interval, streak, lapses, bool(correct))
    due = srs.due_date(day, interval)
    db.execute("""INSERT INTO schedule (exercise_id, due, interval, streak, lapses) VALUES (?, ?, ?, ?, ?)
                  ON CONFLICT(exercise_id) DO UPDATE SET due = excluded.due, interval = excluded.interval,
                  streak = excluded.streak, lapses = excluded.lapses""",
               (exercise_id, due, interval, streak, lapses))
    db.commit()
    return {"due": due, "interval": interval, "streak": streak, "lapses": lapses}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def stats(db, day: datetime.date = None) -> dict:
    day = day or today()
    d = day.isoformat()
    tomorrow = (day + datetime.timedelta(days=1)).isoformat()
    done, right = db.execute("SELECT COUNT(*), COALESCE(SUM(correct), 0) FROM reviews WHERE day = ?", (d,)).fetchone()
    total_done, total_right = db.execute("SELECT COUNT(*), COALESCE(SUM(correct), 0) FROM reviews").fetchone()
    days = [r[0] for r in db.execute("SELECT DISTINCT day FROM reviews ORDER BY day DESC")]
    streak_days = 0
    expected = day
    for x in days:
        if x == expected.isoformat():
            streak_days += 1
            expected -= datetime.timedelta(days=1)
        elif x < expected.isoformat():
            break
    return {
        "today": {"done": done, "correct": right},
        "all_time": {"done": total_done, "correct": total_right},
        "due_now": db.execute("SELECT COUNT(*) FROM schedule WHERE due <= ?", (d,)).fetchone()[0],
        "due_tomorrow": db.execute("SELECT COUNT(*) FROM schedule WHERE due = ?", (tomorrow,)).fetchone()[0],
        "learning": db.execute("SELECT COUNT(*) FROM schedule").fetchone()[0],
        "mastered": db.execute("SELECT COUNT(*) FROM schedule WHERE interval >= 21").fetchone()[0],
        "unseen": db.execute("SELECT COUNT(*) FROM exercises e LEFT JOIN schedule s ON s.exercise_id = e.id "
                             "WHERE s.exercise_id IS NULL").fetchone()[0],
        "day_streak": streak_days,
        "topics": topics(db),
        "weakest": [dict(r) for r in db.execute("""
            SELECT e.topic, COUNT(*) AS done, SUM(r.correct) AS correct
            FROM reviews r JOIN exercises e ON e.id = r.exercise_id
            GROUP BY e.topic HAVING COUNT(*) >= 5
            ORDER BY 1.0 * SUM(r.correct) / COUNT(*) LIMIT 3""")],
    }


# ---------------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------------

def add_message(db, conversation: str, role: str, content: str) -> None:
    db.execute("INSERT INTO messages (conversation, role, content, created) VALUES (?, ?, ?, ?)",
               (conversation, role, content, datetime.datetime.now().isoformat(timespec="seconds")))
    db.commit()


def conversation(db, conversation_id: str, limit: int = 40) -> list:
    rows = db.execute("SELECT role, content FROM messages WHERE conversation = ? ORDER BY id DESC LIMIT ?",
                      (conversation_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]
