# User guide

*[Version française](guide.fr.md) · [Back to the README](../README.md)*

## The program

`curriculum.py` lists 23 topics in teaching order, JLPT N5 then N4. The daily session brings reviews of everything plus new exercises from the **two current topics**. A topic is passed at 80 % right over its last 10–20 answers, or straight away after 5 right answers in a row; « I already know this » in the Progress tab passes it by hand. The next topic then unlocks.

`fill_reserve.py` tops up the current topics and the next one (15 unseen exercises each by default, twice as many for a weak topic): `--target 25`, `--all`, `--topics wa-ga,past`, `--no-llm`.

**Free practice** (Session tab): pick any topics (« All particles », « All N4 »…); « Hard mode » hides the possible answers.

## Topics (`--preset`)

`python make_exercises.py --list-presets` shows them all:

| Preset | Topic |
| --- | --- |
| `wa-ga`, `wo-ga`, `ni-de`, `ni-e`, `wa-mo`, `to-ya`, `kara-made` | N5 particles (the blank is one of the two) |
| `te-form`, `past`, `negative`, `masu`, `tai` | N5 conjugations (the verb is blanked, its dictionary form and reading are shown) |
| `relative-ga`, `relative-form` | N5 relative clauses: が (never は) for the subject of the clause, when the sentence already has its topic (これは私が書いた手紙です); the plain form of the verb before the noun (昨日買った本) |
| `word-order` | N5: put the sentence back in order from the translation (see below) |
| `volitional`, `nagara`, `ba`, `tara`, `causative`, `noni-node` | N4 |
| `mae-ato`, `temo` | N4 clauses: 行く前に (always the dictionary form), 食べた後で (always the past), 降っても (even if) |

Relative clauses, 前に / 後で and ても need no model: the blank, the hint and the explanation come from rules (`clauses.py`).

**Word order** (`word_order.py`): the translation is shown and the sentence is cut into pieces (a word with its particles), shuffled; you click them in order (Backspace takes the last one back). Japanese word order is free for the pieces that carry their particle, so any answer with the predicate last is right; the most usual order is shown when yours differs. To keep that true, only simple sentences are used: one predicate, and what describes a noun (私の, この, 大きい) glued to it.

Custom topics: `--targets "に,で" --pos 格助詞 --title "…"` for particles, `--form te` for conjugations.

## `make_exercises.py` options

| Option | Purpose | Default |
| --- | --- | --- |
| `--preset` / `--targets` / `--form` | what to practice | — |
| `--save` | add to the app's reserve (otherwise an HTML sheet is created) | — |
| `--count` | number of exercises | `10` |
| `--known` | only sentences built from the words you know in Anki | — |
| `--max-unknown` | with `--known`: unknown words allowed per sentence (shown as « New ») | `0` |
| `--known-kanji` | with `--known`: every kanji must be known too | — |
| `--min-words` / `--max-words` | sentence length (≈ difficulty) | `3` / `12` |
| `--pos` | required part of speech, e.g. `格助詞` (case particle) — avoids the で of 読んで | preset |
| `--any-context` | particles: also accept すぐに, には, でも… (by default only simple « noun + particle ») | — |
| `--no-llm` | no check, no explanation (instant) | — |
| `--english` | also accept sentences translated into only one language (by default both French and English are required, so that exercises can go to the shared bank) | — |
| `--level`, `--model`, `--seed` | student level for explanations, Ollama model, reproducible selection | `N5`, `qwen3:14b`, random |

## The app (`server.py`)

`python server.py [--open] [--port 8000] [--model qwen3:14b]`, then http://localhost:8000.

- **Session**: « Today's program » (reviews + new exercises of the current topics) or « Free practice » (chosen topics). Enter = check / next.
- **Words of the sentence**: tap / click a word to open its card, like a short jisho.org page: dictionary form (食べた → 食べる), reading, meanings, JLPT level, « common », whether it is in your Anki deck, and for each kanji its meanings, on / kun readings, JLPT level, school grade and strokes, with a link to Jisho. The blank and the answer are never clickable before you answer; after it, the whole sentence is. Meanings come from Jisho's API through the app (cached in `data/dictionary.db`; offline: your deck and the kanji only), kanji from KANJIDIC (`resources/kanji_info.json`, no network). Not in timed JLPT exams.
- **Readings**: furigana above the kanji (not the whole sentence in kana any more), hidden at first: « Show the reading » shows them, and the app remembers the choice. The verb to conjugate shows its reading with a tap. JLPT questions keep the readings the real test gives.
- **Translation**: hidden at first (« Show the translation »), so you try to understand the sentence first; it comes with the answer anyway. « Always show the translation » on the session screen turns that off. « Put in order » exercises always show it.
- **Teacher**: chat with the tutor. It uses the local model (Ollama running), or Claude / ChatGPT: Progress → « The teacher (AI model) », pick the provider, paste your API key (console.anthropic.com or platform.openai.com; a chat session costs a few cents with the small models). The key is stored in `data/settings.json` and never sent back to the page; with a cloud provider, your chat messages go to that provider. Exercise generation stays local. The status in the top right says which teacher answers and whether it is reachable.
- **Progress**: today's work, streak, reviews due tomorrow, success rate, the program (state of each topic, « I already know this »), « Fill the reserve ».

Everything is stored in `data/coach.db` (SQLite). Nothing leaves your computer (except chat messages if you choose a cloud teacher).

## Anki (`anki_sync.py`)

The collection file (`%APPDATA%\Anki2\<profile>\collection.anki2`) is copied and read directly: Anki can be closed, nothing is ever written to it. The first run detects which note types hold words, kanji and grammar and saves it in `data/anki.json`; `python tools/anki_sync.py --setup` shows what was detected, and you can edit the file (role `ignore` skips a note type). It works with any deck, several decks, or a friend's collection (`--collection path`). `--source ankiconnect` goes through the add-on instead.

## JLPT (`jlpt_questions.py`, JLPT tab)

`python tools/jlpt_questions.py --level N4` (or « Generate questions » in the app) adds 10 questions of each type for the level. The level of a question is the JLPT level of its words (your Anki deck's JLPT sub-decks, or the open lists of `jlpt_data.py`). 表記 needs kanji notes with on'yomi (Anki). 文法形式 and 文脈規定 are checked by the LLM (another choice must not fit too). Rules against ambiguous or too easy questions: one sentence per question (a question never gives away another one's answer); wrong readings built like the real test (another on'yomi of the kanji, long ↔ short vowel, voicing, っ); wrong spellings with same-reading kanji of level N5–N3 that are not real words; no kanji question on words usually written in kana (事); particle pairs that are often both right (は/が, に/へ, と/や…) are never offered together; conjugation choices that would also fit (着て / 着たら / 着れば) are left out; 並べ替え only keeps pieces whose order is fixed by the grammar. Mock exam: questions per type like the real test (without reading comprehension), 1 minute per question, score per section, mistakes back into the reviews.

Furigana in questions: as in the real test, words with a kanji above the question's level (or with no level) get their reading above them, exams included; never the word being tested. In practice, « Show the reading » also puts it on the other words (« Hide the reading » removes those; the test's ones stay). Once answered, each choice shows its reading in kana (in the exam's corrections too).

## Mistakes, undo and reviews by hand

In a session: **↶ Undo my answer** (or Ctrl+Z) forgets a misclick or a typo and puts the review schedule back as it was; on a new exercise it goes back to the previous one. **Actually I don't know it** turns a lucky right answer into a wrong one (back at the end of the session and tomorrow). **Don't show again** suspends an exercise; **⚑ Report a mistake** removes a wrong or ambiguous one for good (it is never generated again). In Progress → **Reviews**: every exercise with its next review, filter by topic or text, and review today, suspend, reactivate or report the ticked ones; « include never seen » adds exercises of the reserve to your reviews.

## Language (French / English)

The app runs in French or English: selector at the top right (saved in `data/settings.json`). The interface, the topic titles and notes, the tutor (prompts, conversation situations, references) and the translations of the sentences follow it. New exercises are generated with a hint and an explanation in both languages; older ones only have French explanations, which are hidden in English. The English translations come from Tatoeba: `python tools/build_bank.py` now keeps them (run it again once; `--french-only` for the old behavior).

## Quality control (`review.py`)

```
python review.py revalidate             # re-check the reserve with the current rules (also done at every startup)
python review.py export --unseen > batch.json
python review.py reject 123 456 --reason "は and が both possible"
python review.py import reviewed.json   # rejections, fixes, new questions
```

When the rules improve, the reserve cleans itself at the next start: exercises that would no longer be generated are removed (and never generated again), accepted answers are updated (に and へ both right with 行く). For a human check, a batch is exported, reviewed (by you, or by Claude), and the reviewed file is dropped in `data/reviews/`: the app applies it at startup. Particle topics whose two answers often both fit only keep the sentences where the grammar decides: は/が (が in a subordinate clause, 誰が, existence; は before a question word), は/も (the translation says « aussi »), を/が (both accepted with たい and potential forms), に/へ and と/や (both accepted where both are right).

## Background start (`install_autostart.py`)

Adds a launcher to the Windows Startup folder: `pythonw server.py` runs without a window; open http://localhost:8000. At startup the server syncs Anki (once a day), waits for Ollama, then tops up the reserve and the JLPT questions (checkboxes in Progress, or `data/settings.json`). Logs: `data/server.log`. Remove with `--uninstall`.

## Measuring the LLM (`evaluate.py`)

```
python tools/evaluate.py                    # 29 hand-made cases in eval/particle_cases.json
python tools/evaluate.py --model qwen3:8b --runs 3
```

Scores how often the check keeps good exercises and drops ambiguous ones and idioms. Run it after changing a prompt or a model, and note the result in `notes/log.md`.

To compare two models on the same new exercises (what they keep, their hints and explanations, the time), without touching the reserve:

```
ollama pull qwen3:30b-a3b
python tools/compare_models.py --models qwen3:14b,qwen3:30b-a3b     # → data/compare/<date>-….json
```

The file is meant to be read side by side (or sent for review): the right answers are in it, the verdicts of each model next to them.

## Updates of the app (`updater.py`)

The Windows app compares its version with the latest GitHub release at startup. Settings (welcome screen, or Progress → The app): **automatic** (downloaded in the background, installed when the app closes), **tell me** (a banner with an « Update » button: the app downloads the new .exe, closes, swaps it and starts again), or **off**. Progress stays in %LOCALAPPDATA%\JapaneseCoach and is never touched.

To publish a version: raise `VERSION` in `coach/updater.py`, `python tools/build_exe.py`, then a GitHub release tagged `v<VERSION>` with `JapaneseCoach.exe` attached, not marked as pre-release (GitHub leaves pre-releases out of « latest »).

## Shared exercise bank (`bank_sync.py`)

Reviewed exercises are published in a separate repository, [Japanese-AI-Coach-bank](https://github.com/Aymeric-Dcn/Japanese-AI-Coach-bank). Every copy of the app downloads what is new at startup (Progress → Shared bank → « Sync now »): the app works without a local model. Only exercise content is shared — never answers, progress or Anki data.

```
python bank_sync.py pull                    # new exercises of the bank (also at startup)
python bank_sync.py contribute              # send the exercises generated here, for review
python bank_sync.py import-inbox --repo ../Japanese-AI-Coach-bank   # maintainer: contributions → reserve
python bank_sync.py publish --repo ../Japanese-AI-Coach-bank        # maintainer: reviewed exercises → bank
```

Review loop: exercises generated locally (or received in the bank's `inbox/`) are marked « not reviewed ». `python review.py export --unreviewed` gives a batch to review; the reviewed batch (rejections, fixes, `approve`) goes to `data/reviews/`, where the running app applies it; `publish` then writes every approved exercise to the bank. Settings in Progress → Shared bank: bank address (default: the public repository), GitHub token (only for a private repository, or to send contributions to `github:owner/repo`).

## Other tools

- `generate_sheet.py`: a lesson + exercises entirely written by the LLM (first version of the project; less reliable).
- `anki_inspect.py`: lists your Anki decks, card counts and note fields.
