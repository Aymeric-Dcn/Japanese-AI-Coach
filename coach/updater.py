"""
Updates of the Windows app: the latest GitHub release is compared with this version; the new .exe is
downloaded next to the data, and a small script replaces the running .exe once it has stopped.

    settings "updates": "auto"   download in the background, install when the app is closed
                        "notify" show a banner with an « Update » button (default)
                        "off"    never look

Progress, settings and exercises live in %LOCALAPPDATA%\\JapaneseCoach, not in the .exe: nothing is lost.
The file is downloaded by the app itself, so Windows does not flag it as « downloaded from the Internet ».
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

VERSION = "0.3.0"   # must match the release tag (v0.2.0) when building the .exe
REPO = "Aymeric-Dcn/Japanese-AI-Coach"
API_URL = os.environ.get("JAPANESE_COACH_UPDATE_URL") or f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "JapaneseCoach.exe"
MODES = ("auto", "notify", "off")

STATE = {"state": "idle", "latest": "", "notes": "", "page": "", "url": "", "size": 0, "progress": 0,
         "error": "", "checked": ""}
_lock = threading.Lock()


def parse(version: str) -> tuple:
    """« v0.2.0 » → (0, 2, 0); a suffix (-beta) is ignored."""
    core = version.strip().lstrip("vV").split("-")[0].split("+")[0]
    try:
        return tuple(int(p) for p in core.split("."))
    except ValueError:
        return ()


def check(timeout: float = 10) -> dict:
    """Asks GitHub for the latest release. Never raises: the state says what happened."""
    with _lock:
        if STATE["state"] in ("downloading", "ready"):
            return dict(STATE)
        STATE.update(state="checking", error="")
    try:
        req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": f"JapaneseCoach/{VERSION}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            release = json.loads(r.read().decode("utf-8"))
        asset = next((a for a in release.get("assets", []) if a.get("name") == ASSET), None)
        newer = parse(release.get("tag_name", "")) > parse(VERSION)
        STATE.update(latest=release.get("tag_name", "").lstrip("vV"), notes=release.get("body") or "",
                     page=release.get("html_url", ""), url=asset.get("browser_download_url", "") if asset else "",
                     size=int(asset.get("size", 0)) if asset else 0,
                     state="available" if newer and asset else "up_to_date")
    except Exception as e:   # offline, rate limit, no release yet…
        STATE.update(state="error", error=str(e)[:200])
    STATE["checked"] = time.strftime("%Y-%m-%d %H:%M")
    return dict(STATE)


def folder() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "JapaneseCoach" / "update"
    base.mkdir(parents=True, exist_ok=True)
    return base


def download() -> bool:
    """Downloads the new .exe (state « ready » when done). Runs in a thread."""
    with _lock:
        if STATE["state"] != "available" or not STATE["url"]:
            return STATE["state"] == "ready"
        STATE.update(state="downloading", progress=0)
    target = folder() / "JapaneseCoach-new.exe"
    part = target.with_suffix(".part")
    try:
        req = urllib.request.Request(STATE["url"], headers={"User-Agent": f"JapaneseCoach/{VERSION}"})
        with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or STATE["size"] or 0)
            done = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                STATE["progress"] = int(100 * done / total) if total else 0
        if STATE["size"] and part.stat().st_size != STATE["size"]:
            raise OSError(f"incomplete download ({part.stat().st_size} / {STATE['size']} bytes)")
        os.replace(part, target)
        STATE.update(state="ready", progress=100)
        return True
    except Exception as e:
        STATE.update(state="available", error=f"download failed: {e}"[:200])
        try:
            part.unlink()
        except OSError:
            pass
        return False


SCRIPT = r"""@echo off
setlocal
set "SRC={src}"
set "DST={dst}"
set /a n=0
:wait
del "%DST%" >nul 2>&1
if not exist "%DST%" goto swap
set /a n+=1
if %n% geq 60 goto end
ping -n 2 127.0.0.1 >nul
goto wait
:swap
move /y "%SRC%" "%DST%" >nul
{restart}
:end
del "%~f0"
"""


def install(restart: bool) -> bool:
    """Starts the script that swaps the .exe once this process has stopped. The caller must then exit.
    Only for the packaged app on Windows."""
    new = folder() / "JapaneseCoach-new.exe"
    if STATE["state"] != "ready" or not new.exists() or os.name != "nt" or not getattr(sys, "frozen", False):
        return False
    script = folder() / "swap.bat"
    script.write_text(SCRIPT.format(src=new, dst=Path(sys.executable),
                                    restart='start "" "%DST%"' if restart else ""), encoding="mbcs")
    flags = 0x08000000 | 0x00000200   # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(["cmd.exe", "/c", str(script)], creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def status(mode: str, packaged: bool) -> dict:
    return dict(STATE, current=VERSION, mode=mode, packaged=packaged,
                can_install=packaged and os.name == "nt")


def start(mode: str, packaged: bool, log=print) -> None:
    """At startup: look for a new version, and in « auto » mode download it in the background."""
    if mode == "off":
        return

    def run():
        result = check()
        if result["state"] == "available":
            log(f"Update available: v{result['latest']} (this is v{VERSION})")
            if mode == "auto" and packaged:
                download()
    threading.Thread(target=run, daemon=True).start()
