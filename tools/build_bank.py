#!/usr/bin/env python3
"""Shortcut for coach.build_bank (see that file for the options): python tools/build_bank.py --help"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the project folder (coach/)

from coach.build_bank import main  # noqa: E402

if __name__ == "__main__":
    main()
