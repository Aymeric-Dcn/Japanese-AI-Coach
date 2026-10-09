#!/usr/bin/env python3
"""Shortcut for coach.anki.anki_sync (see that file for the options): python tools/anki_sync.py --help"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the project folder (coach/)

from coach.anki.anki_sync import main  # noqa: E402

if __name__ == "__main__":
    main()
