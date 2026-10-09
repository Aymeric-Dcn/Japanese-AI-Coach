#!/usr/bin/env python3
"""Shortcut for coach.exercises.fill_reserve (see that file for the options): python tools/fill_reserve.py --help"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the project folder (coach/)

from coach.exercises.fill_reserve import main  # noqa: E402

if __name__ == "__main__":
    main()
