# Test log

## 2026-09-27 — First test: particles に and で (N5)

Hardware: RTX 4070 Super 12 GB, 32 GB RAM, Ollama.

**gemma3:12b — rejected**
- Wrong explanations: for 学校で勉強します and 家で会います it claims に is used.
- Blanks hide the noun instead of the particle: impossible questions.
- Several exercises with no usable answer.

**qwen3:14b — kept**
- 7/10 right on the first try, mostly correct.
- Errors: example 本を読んでいる listed under the で rule; wrong explanation « で indique l'action en cours »; one off-topic exercise (を); readings in romaji instead of hiragana.
- Same misplaced-blank problem as Gemma on some exercises.

**Script fixes**
- The model surrounds the answer with `【 】` in a full sentence; the script makes the blank itself.
- `--answers` option: closed list of answers, exercises outside the list are dropped.
- Stricter prompt (format example, hiragana required, examples consistent with their rule).
- Generates a few extra exercises and retries if needed to reach the requested count.

**Conclusion**: a local model invents both the sentences *and* their answers, with errors. Chosen direction: an exercise bank built from real sentences (Tatoeba) + a morphological analyzer, the LLM only annotating and explaining.

## 2026-09-27 — Bank of real sentences

- `build_bank.py`: Tatoeba (Japanese with a French translation) → SudachiPy → SQLite bank.
- `make_exercises.py`: blanks made by the script on the original sentence, part-of-speech filter (`--pos 格助詞` skips the で of 読んで), a single target per sentence, balanced alternation of answers.
- The LLM (qwen3:14b, thinking mode off) only: flags whether another answer would work (sentence dropped), writes the hint and explanation.
- Tested on simulated data.

## 2026-09-27 — First run on the real bank

- Bank: 40,396 sentences with a French translation, analyzed in 5 s.
- に/で: 8,508 and 2,446 candidate sentences. 10 exercises kept, **28 dropped** in 187 s (~5 s per sentence).
- Problems: Qwen drops far too many (e.g. 彼は車で来た); unhelpful blanks (すぐに, 日本語には, 誰でも); sometimes hard vocabulary (患者, 病名, 通知).
- Fixes:
  - particles: only « noun + particle » cases, no stacked particle (には, でも…); `--any-context` to disable;
  - check: Qwen writes each alternative sentence and judges whether it is correct, natural and faithful to the translation (instead of a list of "possible" answers); the drop reason is printed;
  - SudachiPy 0.7 warning fixed (`tokenizer()` instead of `create()`).
- Next step for difficulty: filter vocabulary with Anki.

## 2026-09-27 — Code in English

- Files, identifiers, CLI options, console messages and JSON keys renamed to English: `build_bank.py`, `make_exercises.py`, `generate_sheet.py`, shared `sheet.py`; bank is now `data/bank.db`, sheets go to `sheets/`.
- LLM prompts are now written in English, still asking for French explanations. To watch: does this change the quality of Qwen's answers?
- Docs: `README.md` (English) and `README.fr.md` (French). The sheet interface stays in French.

## 2026-09-27 — Second run on the real bank (after the fixes)

- に/で: 7,128 and 1,908 candidates. **10 kept, 1 dropped in 58 s** (was 10 kept / 28 dropped in 187 s).
- The only drop was a Qwen mistake: asked to write the に variant, it copied the original で sentence and judged it correct.
- Some kept sentences were poor examples: fixed expressions (人によって, お目にかかる, 当てにする).
- Fixes:
  - alternative sentences are now built by the script; Qwen only judges them;
  - new `good_example` judgement: Qwen drops idioms / fixed expressions and grammar far above the level, with a reason;
  - compound particles (によって, にとって, について, に対して, に関して…) are skipped before asking the LLM.

## 2026-09-27 — Third run (stricter selection)

- **10 kept, 0 dropped in 54 s.** About 8–9 of 10 are good exercises (日曜日に, 通販で, 家で, 17世紀に, 真夏日になる…).
- Bad one: 今夜は本当に疲れたよ — 本当に is an adverb (noun that can act as an adjective + に), not a particle use; Qwen still judged it a good example.
- Fix: the bank now stores SudachiPy's sub-sub-category; に after a « 形状詞可能 » noun (本当に, 大切に, 静かに…) is skipped. Needs `build_bank.py` to be run again.
- 0 drops out of 10: Qwen may now be too lenient on `good_example`; keep an eye on it.
- gemma3:12b removed from the machine (`ollama rm gemma3:12b`).

## 2026-09-27 — Fourth run

- 10 kept, 0 dropped in 53 s. 7/10 good. Bad: それで (conjunction « so »), 何で (« why »), 私のために (ために = purpose, separate grammar point). Qwen's `good_example` check lets these through.
- Fix: nouns forming fixed words with the particle (それ, 何/なん, ため) are skipped by the script.
- AnkiConnect installed and reachable. Added `anki_inspect.py` to list decks, card counts and note fields before writing the sync.

## 2026-09-27 — Anki sync

- Collection: Full Japanese Study Deck. Mature (interval ≥ 21 d): 723 N5 + 571 N4 vocab cards, 311 kanji (79 N5, 160 N4, 72 N3). Note types: FJSD-Word, FJSD-Kanji, FJSD-Grammar, FJSD-Kana, FJSD-Radical.
- `anki_inspect.py` was too slow (read every note, ~50k); now reads one sample note per note type.
- `anki_sync.py`: known FJSD-Word / FJSD-Kanji notes → `data/known.json` (every kanji form and reading from the ruby HTML).
- `make_exercises.py --known --max-unknown N [--known-kanji]`: content words (nouns, verbs, adjectives, adverbs…) checked by dictionary form, surface and reading; particles, auxiliaries, numbers, proper nouns and light verbs always count as known. Unknown words are shown on the sheet as « Nouveau ».
- Tested with a simulated AnkiConnect and bank; to test on the real collection.

## 2026-09-27 — First run with the Anki sync

- `anki_sync.py`: 1,294 known word notes → 2,776 forms; 311 kanji (1,014 kanji counting those inside known words).
- `--known --max-unknown 1`: 4,287 に and 1,090 で candidates (was 6,855 / 1,908 without the filter). 10 kept, 0 dropped in 55 s.
- ~9/10 good (日本に帰る, 交通事故で, 一人で, この点で, タクシーで…). Weak one: 楽しみにしています (fixed expression 楽しみにする), let through by Qwen.
- Qwen dropped nothing for the third run in a row: its `good_example` check looks weak; a test set is needed to measure it.

## 2026-09-27 — The app: sessions, spaced repetition, chat, test set

- New `data/coach.db` (store.py): exercise reserve, every answer, review schedule, chat history.
- Spaced repetition (srs.py): first attempt only; wrong → tomorrow (and once more at the end of the session); right → 1, 3, 7, 16 days, then ×2.3 (max 180).
- `make_exercises.py --save` fills the reserve; presets for particles (ni-de, wa-ga…) and conjugations (te-form, past, negative, masu, tai: verb + ending blanked, dictionary form as cue, kana spelling accepted).
- `server.py` + `web/`: standard library only, so no install needed. Tabs Session / Prof / Progrès.
- Chat (tutor.py): French tutor prompt, student context (vocabulary size from Anki, last 8 mistakes), SudachiPy analysis of Japanese sentences sent for correction, « Demander au prof » from an exercise; answers streamed from Ollama.
- `evaluate.py` + `eval/particle_cases.json`: 29 hand-made に/で cases (18 keep, 4 ambiguous, 7 not_example) to score the LLM check.
- Tested here with simulated SudachiPy / Ollama and headless Chromium (session flow, requeue of missed exercises, schedule, chat streaming, progress). Not yet tested with the real Qwen, SudachiPy and Anki.
