"""
Spaced repetition: when should an exercise come back?

Deliberately simple (Leitner-like):
  - wrong answer  → back tomorrow, streak reset;
  - right answer  → 1 day, then 3, 7, 16 days, then ×2.3 each time (max 180 days).
Only the FIRST attempt of a review counts.
"""

import datetime

FIRST_STEPS = [1, 3, 7, 16]
GROWTH = 2.3
MAX_INTERVAL = 180


def next_state(interval: int, streak: int, lapses: int, correct: bool) -> tuple:
    """(interval, streak, lapses) before the answer → (interval, streak, lapses) after it."""
    if not correct:
        return 1, 0, lapses + 1
    streak += 1
    if streak <= len(FIRST_STEPS):
        interval = FIRST_STEPS[streak - 1]
    else:
        interval = min(MAX_INTERVAL, round(max(interval, 1) * GROWTH))
    return interval, streak, lapses


def due_date(today: datetime.date, interval: int) -> str:
    return (today + datetime.timedelta(days=interval)).isoformat()
