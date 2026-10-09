#!/usr/bin/env python3
"""Shortcut for coach.exercises.make_exercises (see that file for the options): python make_exercises.py --help"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))   # the project folder (coach/)

from coach.exercises.make_exercises import main  # noqa: E402

if __name__ == "__main__":
    main()
