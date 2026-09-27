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
