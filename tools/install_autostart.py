#!/usr/bin/env python3
"""
Starts the app automatically when you log into Windows, in the background (no window).

    python tools/install_autostart.py              # install
    python tools/install_autostart.py --uninstall  # remove

It adds a small launcher (JapaneseCoach.vbs) to your Startup folder. At each start, the server
syncs Anki (once a day) and tops up the exercise reserve as soon as Ollama is available
(settings in data/settings.json). Then just open http://localhost:8000.
Logs go to data/server.log.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))   # the project folder (coach/)

import argparse
import os
import platform
import sys
from pathlib import Path

NAME = "JapaneseCoach.vbs"


def startup_folder() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def main() -> None:
    p = argparse.ArgumentParser(description="Start Japanese Coach automatically with Windows.")
    p.add_argument("--uninstall", action="store_true")
    args = p.parse_args()

    if platform.system() != "Windows":
        sys.exit("Only for Windows. On macOS/Linux, add « python server.py » to your login items instead.")
    target = startup_folder() / NAME
    if args.uninstall:
        if target.exists():
            target.unlink()
            print(f"✓ Removed {target}")
        else:
            print("Nothing to remove.")
        return

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    project = Path(__file__).resolve().parents[1]
    vbs = (
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.CurrentDirectory = "{project}"\r\n'
        f'sh.Run """{pythonw}"" ""{project / "server.py"}""", 0, False\r\n'
    )
    target.write_text(vbs, encoding="utf-8")
    print(f"✓ Installed: {target}")
    print("  The app will start in the background at your next login (http://localhost:8000).")
    print("  To start it right now without a window, double-click that file, or run: python server.py")


if __name__ == "__main__":
    main()
