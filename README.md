# Japanese Coach AI

*[Version française](README.fr.md)*

A personal Japanese tutor that runs **entirely on your computer**: a small web app with daily fill-in-the-blank exercises built from real sentences, spaced repetition of your mistakes, and a chat with a tutor powered by a local LLM ([Ollama](https://ollama.com)).

> A learning project: learning Japanese, and learning how to set up an LLM along the way.

## How it works

```
Tatoeba ──► build_bank.py ──► data/bank.db (real sentences, split by SudachiPy)
Anki ─────► anki_sync.py ───► data/known.json (words and kanji you know)
                    │
                    ▼
            make_exercises.py --save   (picks sentences, makes the blank,
                    │                   Qwen drops doubtful ones and explains)
                    ▼
            data/coach.db ◄──► server.py + web/  →  http://localhost:8000
            (reserve, answers,          Session · Prof (chat) · Progrès
             review schedule, chat)
```

- **Exercises from real sentences**: the answer is the original text, readings come from the analyzer; the LLM invents nothing, it only filters and explains.
- **Your level**: with the Anki sync, only sentences whose words you already know (or all but one: « i+1 »).
- **Spaced repetition**: a missed exercise comes back at the end of the session and the next day; a right one after 1, 3, 7, 16 days, then longer.
- **Tutor chat**: questions, explanations, correction of your own sentences (analyzed by SudachiPy first), « Demander au prof » from any exercise. The tutor knows your recent mistakes.

The app interface, hints and explanations are in French.

## Installation

Tested on: Windows, RTX 4070 Super (12 GB VRAM), 32 GB RAM.

1. **Ollama**: install from [ollama.com/download](https://ollama.com/download), then a model:
   ```
   ollama pull qwen3:14b
   ```
2. **Python 3.9+**: [python.org](https://www.python.org/downloads/) (tick *Add python.exe to PATH*), then:
   ```
   pip install -r requirements.txt
   ```
3. **Japanese keyboard**: Windows Settings → Time & language → Language & region → add *Japanese*. Switch with `Windows + Space`.
4. **Anki** (optional): install the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on (code `2055492159`).

## Getting started

```
python build_bank.py                       # once: download and analyze Tatoeba (a few minutes)
python anki_sync.py                        # with Anki open: your known words → data/known.json
python server.py --open                    # the app, on http://localhost:8000
```

Then in the app: **Progrès → Remplir la réserve** (or `python fill_reserve.py` in a terminal). It adds exercises to the topics in progress (~5 s each with Qwen); sessions are then instant. Run `anki_sync.py` again when your Anki progresses.

### The programme

`curriculum.py` lists 18 topics in teaching order, JLPT N5 then N4. The daily session brings reviews of everything plus new exercises from the **two current topics**. A topic is passed at 80 % right over its last 10–20 answers, or straight away after 5 right answers in a row; « Je maîtrise déjà » in the Progrès tab passes it by hand. The next topic then unlocks.

`fill_reserve.py` tops up the current topics and the next one (15 unseen exercises each by default, twice as many for a weak topic): `--target 25`, `--all`, `--topics wa-ga,past`, `--no-llm`.

**Entraînement libre** (Session tab): pick any topics (« Toutes les particules », « Tout N4 »…); « Mode difficile » hides the possible answers.

### Topics (`--preset`)

`python make_exercises.py --list-presets` shows them all:

| Preset | Topic |
| --- | --- |
| `wa-ga`, `wo-ga`, `ni-de`, `ni-e`, `wa-mo`, `to-ya`, `kara-made` | N5 particles (the blank is one of the two) |
| `te-form`, `past`, `negative`, `masu`, `tai` | N5 conjugations (the verb is blanked, its dictionary form and reading are shown) |
| `volitional`, `nagara`, `ba`, `tara`, `causative`, `noni-node` | N4 |

Custom topics: `--targets "に,で" --pos 格助詞 --title "…"` for particles, `--form te` for conjugations.

### `make_exercises.py` options

| Option | Purpose | Default |
| --- | --- | --- |
| `--preset` / `--targets` / `--form` | what to practise | — |
| `--save` | add to the app's reserve (otherwise an HTML sheet is created) | — |
| `--count` | number of exercises | `10` |
| `--known` | only sentences built from the words you know in Anki | — |
| `--max-unknown` | with `--known`: unknown words allowed per sentence (shown as « Nouveau ») | `0` |
| `--known-kanji` | with `--known`: every kanji must be known too | — |
| `--min-words` / `--max-words` | sentence length (≈ difficulty) | `3` / `12` |
| `--pos` | required part of speech, e.g. `格助詞` (case particle) — avoids the で of 読んで | preset |
| `--any-context` | particles: also accept すぐに, には, でも… (by default only simple « noun + particle ») | — |
| `--no-llm` | no check, no explanation (instant) | — |
| `--english` | accept sentences translated only into English (run `build_bank.py --english` first) | — |
| `--level`, `--model`, `--seed` | student level for explanations, Ollama model, reproducible selection | `N5`, `qwen3:14b`, random |

### The app (`server.py`)

`python server.py [--open] [--port 8000] [--model qwen3:14b]`, then http://localhost:8000.

- **Session**: « Programme du jour » (reviews + new exercises of the current topics) or « Entraînement libre » (chosen topics). Enter = check / next.
- **Prof**: chat with the tutor. Needs Ollama running; the status in the top right says whether it is reachable.
- **Progrès**: today's work, streak, reviews due tomorrow, success rate, the programme (state of each topic, « Je maîtrise déjà »), « Remplir la réserve ».

Everything is stored in `data/coach.db` (SQLite). Nothing leaves your computer.

### Measuring the LLM (`evaluate.py`)

```
python evaluate.py                    # 29 hand-made cases in eval/particle_cases.json
python evaluate.py --model qwen3:8b --runs 3
```

Scores how often the check keeps good exercises and drops ambiguous ones and idioms. Run it after changing a prompt or a model, and note the result in `notes/log.md`.

### Other tools

- `generate_sheet.py`: a lesson + exercises entirely written by the LLM (first version of the project; less reliable).
- `anki_inspect.py`: lists your Anki decks, card counts and note fields.

## Project layout

```
server.py           the app: web server + JSON API (standard library only)
web/                the interface (index.html, app.css, app.js)
store.py            progress database: reserve, answers, schedule, chat
srs.py              spaced repetition intervals
curriculum.py       the study programme: topics N5 → N4, progression rules
fill_reserve.py     tops up the reserve following the programme
tutor.py            the chat tutor: prompt, student context, sentence analysis
llm.py              Ollama client (structured answers, streaming)
build_bank.py       Tatoeba → SudachiPy → data/bank.db
make_exercises.py   exercises from the bank → reserve (--save) or HTML sheet
anki_sync.py        known words and kanji from Anki → data/known.json
evaluate.py, eval/  test set to measure the LLM check
generate_sheet.py   LLM-generated sheet;  sheet.py: HTML sheets
notes/log.md        test log (models, prompts, results)
```

## Roadmap

- [x] Fill-in-the-blank sheets generated by a local LLM
- [x] **Sentence bank**: Tatoeba + SudachiPy, exact blanks, the LLM only filters and explains
- [x] **Anki sync**: sentences built from the words I know (i+1)
- [x] Particle and **conjugation** topics (て-form, past, negative, ます, たい)
- [x] **Local app** with daily sessions, **spaced repetition** and progress
- [x] **Chat** with the tutor (explanations, correcting my sentences, questions about an exercise)
- [x] **Test set** to measure the LLM check
- [ ] Improve the check using the test set (prompt, model)
- [ ] Vocabulary checks with [JMdict](https://www.edrdg.org/jmdict/j_jmdict.html)
- [x] **Programme** N5 → N4 with progression, free practice, « Je maîtrise déjà »
- [x] Fill the reserve from the app
- [ ] More exercise types (translation, reordering, listening)

## Data sources and licences

This repository only contains code, prompts and documentation. Downloaded or personal data (`data/`, `sources/`, SQLite databases, generated sheets) is excluded by `.gitignore`. No content taken from copyrighted textbooks may be published here.

Open sources: Tatoeba (CC BY 2.0 FR), JMdict / KANJIDIC (CC BY-SA 4.0, EDRDG), Tae Kim's grammar guide (CC BY-NC-SA 3.0).
