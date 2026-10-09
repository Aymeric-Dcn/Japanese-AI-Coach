# Japanese Coach on a Raspberry Pi (phone + PC, one progress)

*Version française : [raspberry-pi.fr.md](raspberry-pi.fr.md)*

This is optional. The app on your PC (the `.exe` or `python server.py`) works exactly as before without it.

The idea: a small always-on computer (a Raspberry Pi 2, 3 or newer) runs the app, and you open it from your
phone **and** your PC. There is one database, so reviews, streaks and progress are the same everywhere.
[Tailscale](https://tailscale.com) makes it reachable from anywhere (4G included) and only by your own devices.

```
 phone ─┐                                    ┌─ Ollama on the PC (optional, when the PC is on)
        ├── Tailscale (HTTPS) ── Raspberry Pi ┤
 PC ────┘        app + progress (coach.db)    └─ or a cloud model (Claude / OpenAI key)
```

What runs where:

| | On the Pi | Stays on the PC |
|---|---|---|
| Exercises, reviews, JLPT exams, progress | ✓ | |
| New exercises from the shared bank | ✓ (at start, then every day) | |
| Generating exercises from your Anki deck | | ✓ (then review + publish to the bank: the Pi picks them up) |
| Teacher chat | ✓ with a cloud key, or with the PC's Ollama when the PC is on | |

The Pi only needs Python: no SudachiPy, no Ollama, no Anki. A Pi 2 (1 GB of RAM) is enough.

## 1. Check the Pi

```sh
python3 --version     # 3.8 or newer (Raspberry Pi OS « Bullseye » = 3.9, « Bookworm » = 3.11)
tailscale status      # the Pi, your PC and your phone should be listed
```

With Python 3.7 or older (Raspberry Pi OS « Buster »), flash a recent **Raspberry Pi OS Lite** first
(Raspberry Pi Imager; the 32-bit version for a Pi 2).

## 2. Install the app

```sh
sudo apt install -y git
git clone https://github.com/Aymeric-Dcn/Japanese-AI-Coach.git
cd Japanese-AI-Coach
mkdir -p data          # your data is not in git: this folder receives it in the next step
```

## 3. Bring your progress from the PC

In PowerShell on the PC, from the app folder (`C:\Projects\Japanese-AI-Coach`; for the `.exe`:
`%LOCALAPPDATA%\JapaneseCoach`). Replace `pi@raspberrypi` with your user and the Pi's Tailscale name:

```powershell
scp data\coach.db data\settings.json data\known.json data\lexicon.db data\grammar.json data\kanji.json pi@raspberrypi:Japanese-AI-Coach/data/
```

- `coach.db` = exercises and progress, `known.json` + `lexicon.db` + `grammar.json` + `kanji.json` = what your Anki
  deck says you know, `settings.json` = settings (API key included).
- Do not copy `bank.db` (240 MB, only for generating).
- Close the app on the PC first, so `coach.db` is complete.

From now on, **the Pi's copy is the one that counts**: practice on the Pi's address, not in the app on the PC
(otherwise the two progress files go different ways). After a new Anki sync on the PC, copy `known.json`,
`lexicon.db`, `grammar.json` and `kanji.json` again so the Pi knows your new words.

## 4. Start it as a service

```sh
sh deploy/install-pi.sh
```

The app now starts with the Pi and restarts by itself if it stops. Useful commands:

```sh
journalctl -u japanese-coach -f            # the log
sudo systemctl restart japanese-coach      # after a change
git pull && sudo systemctl restart japanese-coach   # update the app
```

## 5. Open it from the phone and the PC

```sh
sudo tailscale serve --bg 8000
```

Tailscale prints an address like `https://raspberrypi.your-tailnet.ts.net`. Only devices of your tailnet can open
it (if Tailscale asks, enable HTTPS certificates in the admin console: DNS → HTTPS Certificates).

- **Phone**: open the address in Chrome (Android) or Safari (iPhone), then *Add to Home screen* / *Install app*.
  It opens full screen like an app, with its own icon.
- **PC**: open the same address in Edge or Chrome, then ⋯ → *Apps* → *Install this site as an app*.

The app itself still listens only on the Pi (127.0.0.1): Tailscale is the only way in.

## 5b. Words, readings and translations of your exercises

The Pi cannot compute the words of a sentence (clickable words, furigana) or the older exercises' English translations itself: it has neither SudachiPy nor `bank.db`. Your PC sends them, in one command (also after each new generation):

```powershell
python bank_sync.py send-texts --to https://raspberrypi.your-tailnet.ts.net
```

Only what an exercise lacks is added; progress is not touched. Exercises of the shared bank also get them from the bank.

## 6. The teacher (chat)

Two choices, both in `data/settings.json` on the Pi (or through Progress → The app → Run the welcome wizard again):

- **A cloud key** (Claude or OpenAI): works at any time, the PC can be off. Simplest.
- **The PC's Ollama**, when the PC is on. On the PC, make Ollama listen on the network, once:
  ```powershell
  setx OLLAMA_HOST 0.0.0.0
  ```
  then quit Ollama (icon near the clock) and start it again. On the Pi, add the PC's Tailscale name to
  `data/settings.json`:
  ```json
  "ollama_url": "my-pc"
  ```
  (`my-pc`, `100.x.y.z` or `http://my-pc:11434` all work) and `sudo systemctl restart japanese-coach`.
  Ollama has no password: Windows' firewall and Tailscale keep it private, but do not open port 11434 on your router.

## Options of `server.py`

| | |
|---|---|
| `--port 8000` | the port |
| `--host 127.0.0.1` | where to listen. Default: this computer only. `--host 0.0.0.0` = every network of the computer: there is no password, so only on a private network |
| `--ollama my-pc:11434` | the Ollama to use (otherwise the `ollama_url` setting, otherwise this computer) |
