#!/usr/bin/env python3
"""
Builds the Windows app: dist/JapaneseCoach.exe — one file, no console, nothing else to install.

    pip install pyinstaller
    python build_exe.py

The .exe contains the server and the interface (standard library only). It opens in its own window
(Edge or Chrome in app mode, the browser if neither is found) and stops when that window is closed. On first
start it shows the welcome screen, keeps its data in %LOCALAPPDATA%\\JapaneseCoach, and downloads the
reviewed exercises of the shared bank. The chat and new exercises need Ollama (optional).
Not included: the sentence bank and SudachiPy (only needed to generate exercises, i.e. with Ollama and
the full project).
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller is missing: pip install pyinstaller")
    icon = ROOT / "docs" / "icon.ico"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--noconsole",
           "--name", "JapaneseCoach", "--add-data", f"{ROOT / 'web'}{os.pathsep}web",
           "--exclude-module", "sudachipy", "--exclude-module", "sudachidict_core",
           "--exclude-module", "tkinter", "--exclude-module", "unittest"]
    if icon.exists():
        cmd += ["--icon", str(icon)]
    cmd.append(str(ROOT / "server.py"))
    subprocess.run(cmd, check=True, cwd=ROOT)
    exe = ROOT / "dist" / ("JapaneseCoach.exe" if os.name == "nt" else "JapaneseCoach")
    print(f"\n✓ {exe} ({exe.stat().st_size / 1e6:.1f} MB). Give this single file to your friends.")


if __name__ == "__main__":
    main()
