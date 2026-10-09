#!/usr/bin/env python3
"""Shortcut for coach.exercises.jlpt_questions (see that file for the options): python tools/jlpt_questions.py --help"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the project folder (coach/)

from coach.exercises.jlpt_questions import main  # noqa: E402

if __name__ == "__main__":
    main()
