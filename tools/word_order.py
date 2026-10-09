#!/usr/bin/env python3
"""Shortcut for coach.exercises.word_order (see that file for the options): python tools/word_order.py --help"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the project folder (coach/)

from coach.exercises.word_order import main  # noqa: E402

if __name__ == "__main__":
    main()
