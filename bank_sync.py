#!/usr/bin/env python3
"""Shortcut for coach.bank_sync (see that file for the options): python bank_sync.py --help"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))   # the project folder (coach/)

from coach.bank_sync import main  # noqa: E402

if __name__ == "__main__":
    main()
