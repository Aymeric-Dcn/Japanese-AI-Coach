# User guide

*[Version française](guide.fr.md) · [Back to the README](../README.md)*

## The programme

`curriculum.py` lists 18 topics in teaching order, JLPT N5 then N4. The daily session brings reviews of everything plus new exercises from the **two current topics**. A topic is passed at 80 % right over its last 10–20 answers, or straight away after 5 right answers in a row; « Je maîtrise déjà » in the Progrès tab passes it by hand. The next topic then unlocks.

`fill_reserve.py` tops up the current topics and the next one (15 unseen exercises each by default, twice as many for a weak topic): `--target 25`, `--all`, `--topics wa-ga,past`, `--no-llm`.

**Entraînement libre** (Session tab): pick any topics (« Toutes les particules », « Tout N4 »…); « Mode difficile » hides the possible answers.

## Topics (`--preset`)

`python make_exercises.py --list-presets` shows them all:

| Preset | Topic |
| --- | --- |
| `wa-ga`, `wo-ga`, `ni-de`, `ni-e`, `wa-mo`, `to-ya`, `kara-made` | N5 particles (the blank is one of the two) |
| `te-form`, `past`, `negative`, `masu`, `tai` | N5 conjugations (the verb is blanked, its dictionary form and reading are shown) |
| `volitional`, `nagara`, `ba`, `tara`, `causative`, `noni-node` | N4 |

Custom topics: `--targets "に,で" --pos 格助詞 --title "…"` for particles, `--form te` for conjugations.

## `make_exercises.py` options

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
| `--english` | also accept sentences translated into only one language (by default both French and English are required, so that exercises can go to the shared bank) | — |
| `--level`, `--model`, `--seed` | student level for explanations, Ollama model, reproducible selection | `N5`, `qwen3:14b`, random |

## The app (`server.py`)

`python server.py [--open] [--port 8000] [--model qwen3:14b]`, then http://localhost:8000.

- **Session**: « Programme du jour » (reviews + new exercises of the current topics) or « Entraînement libre » (chosen topics). Enter = check / next.
- **Prof**: chat with the tutor. It uses the local model (Ollama running), or Claude / ChatGPT: Progrès → « The teacher (AI model) », pick the provider, paste your API key (console.anthropic.com or platform.openai.com; a chat session costs a few cents with the small models). The key is stored in `data/settings.json` and never sent back to the page; with a cloud provider, your chat messages go to that provider. Exercise generation stays local. The status in the top right says which teacher answers and whether it is reachable.
- **Progrès**: today's work, streak, reviews due tomorrow, success rate, the programme (state of each topic, « Je maîtrise déjà »), « Remplir la réserve ».

Everything is stored in `data/coach.db` (SQLite). Nothing leaves your computer (except chat messages if you choose a cloud teacher).

## Anki (`anki_sync.py`)

The collection file (`%APPDATA%\Anki2\<profile>\collection.anki2`) is copied and read directly: Anki can be closed, nothing is ever written to it. The first run detects which note types hold words, kanji and grammar and saves it in `data/anki.json`; `python anki_sync.py --setup` shows what was detected, and you can edit the file (role `ignore` skips a note type). It works with any deck, several decks, or a friend's collection (`--collection path`). `--source ankiconnect` goes through the add-on instead.

## JLPT (`jlpt_questions.py`, JLPT tab)

`python jlpt_questions.py --level N4` (or « Générer des questions » in the app) adds 10 questions of each type for the level. The level of a question is the JLPT level of its words (your Anki deck's JLPT sub-decks, or the open lists of `jlpt_data.py`). 表記 needs kanji notes with on'yomi (Anki). 文法形式 and 文脈規定 are checked by the LLM (another choice must not fit too). Rules against ambiguous or too easy questions: one sentence per question (a question never gives away another one's answer); wrong readings built like the real test (another on'yomi of the kanji, long ↔ short vowel, voicing, っ); wrong spellings with same-reading kanji of level N5–N3 that are not real words; no kanji question on words usually written in kana (事); particle pairs that are often both right (は/が, に/へ, と/や…) are never offered together; conjugation choices that would also fit (着て / 着たら / 着れば) are left out; 並べ替え only keeps pieces whose order is fixed by the grammar. Mock exam: questions per type like the real test (without reading comprehension), 1 minute per question, score per section, mistakes back into the reviews.

## Mistakes, undo and reviews by hand

In a session: **↶ Annuler ma réponse** (or Ctrl+Z) forgets a misclick or a typo and puts the review schedule back as it was; on a new exercise it goes back to the previous one. **En fait je ne maîtrise pas** turns a lucky right answer into a wrong one (back at the end of the session and tomorrow). **Ne plus proposer** suspends an exercise; **⚑ Signaler une erreur** removes a wrong or ambiguous one for good (it is never generated again). In Progrès → **Révisions**: every exercise with its next review, filter by topic or text, and review today, suspend, reactivate or report the ticked ones; « jamais vus » adds exercises of the reserve to your reviews.

## Language (French / English)

The app runs in French or English: selector at the top right (saved in `data/settings.json`). The interface, the topic titles and notes, the tutor (prompts, conversation situations, references) and the translations of the sentences follow it. New exercises are generated with a hint and an explanation in both languages; older ones only have French explanations, which are hidden in English. The English translations come from Tatoeba: `python build_bank.py` now keeps them (run it again once; `--french-only` for the old behaviour).

## Quality control (`review.py`)

```
python review.py revalidate             # re-check the reserve with the current rules (also done at every startup)
python review.py export --unseen > batch.json
python review.py reject 123 456 --reason "は and が both possible"
python review.py import reviewed.json   # rejections, fixes, new questions
```

When the rules improve, the reserve cleans itself at the next start: exercises that would no longer be generated are removed (and never generated again), accepted answers are updated (に and へ both right with 行く). For a human check, a batch is exported, reviewed (by you, or by Claude), and the reviewed file is dropped in `data/reviews/`: the app applies it at startup. Particle topics whose two answers often both fit only keep the sentences where the grammar decides: は/が (が in a subordinate clause, 誰が, existence; は before a question word), は/も (the translation says « aussi »), を/が (both accepted with たい and potential forms), に/へ and と/や (both accepted where both are right).

## Background start (`install_autostart.py`)

Adds a launcher to the Windows Startup folder: `pythonw server.py` runs without a window; open http://localhost:8000. At startup the server syncs Anki (once a day), waits for Ollama, then tops up the reserve and the JLPT questions (checkboxes in Progrès, or `data/settings.json`). Logs: `data/server.log`. Remove with `--uninstall`.

## Measuring the LLM (`evaluate.py`)

```
python evaluate.py                    # 29 hand-made cases in eval/particle_cases.json
python evaluate.py --model qwen3:8b --runs 3
```

Scores how often the check keeps good exercises and drops ambiguous ones and idioms. Run it after changing a prompt or a model, and note the result in `notes/log.md`.

To compare two models on the same new exercises (what they keep, their hints and explanations, the time), without touching the reserve:

```
ollama pull qwen3:30b-a3b
python compare_models.py --models qwen3:14b,qwen3:30b-a3b     # → data/compare/<date>-….json
```

The file is meant to be read side by side (or sent for review): the right answers are in it, the verdicts of each model next to them.

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
