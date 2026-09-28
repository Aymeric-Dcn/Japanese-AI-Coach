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

## 2026-09-27 — First real use of the app

- Reserve: 20 に/で (0 dropped, 101 s) and 20 て-form (0 dropped, 96 s). First session: 10 exercises, 6 right on the first try. Conjugation exercises and the overall feedback: good.
- Chat: answer on 手伝ってくれる was on the right track but with a wrong example (彼は私を待ってください) and dubious extra rules on 〜ていく / 〜てくる; numbered list shown as 1., 1., 1.
- Fixes: tutor prompt (few, simple, checked examples; stay on the question; no emoji), chat temperature 0.5 → 0.3; numbered lists keep their numbers.
- Conjugations: the verb to conjugate is now shown above the sentence with its reading (手伝う（てつだう）), and « réponse en kanji ou en kana » (the kana spelling was already accepted).
- « Mode difficile » checkbox: hides the possible answers for particle exercises.
- Layout: long sentences and inputs no longer overflow their card.
- Odd one: 彼女は茶色い目をしている (て-form of する in 目をしている, « to have brown eyes »): correct but idiomatic.
- Ideas for next steps: JLPT levels, choose what to work on, free particle mode (any particle, none shown), a curriculum for the daily session with progression, extra exercises by topic, more practice on weak points.

## 2026-09-27 — Programme, free practice, filling from the app

- `curriculum.py`: 18 topics, N5 (masu, は/が, を/が, に/で, ない, に/へ, た, は/も, と/や, て, から/まで, たい) then N4 (volitional, ながら, ば, たら, のに/ので, causative).
- Progression (store.topic_states): passed = ≥ 80 % over the last 10–20 answers, or ≥ 5 answers all right (fast track for easy topics), or « Je maîtrise déjà »; the first 2 topics not passed are « current »; the rest are locked. Daily session = all reviews due + new exercises from the current topics.
- `fill_reserve.py` (and « Remplir la réserve » in the app, background job with live log): tops up current topics + the next one to 15 unseen exercises (30 for a weak topic < 70 %).
- Free practice: choose topics, quick picks (all particles → hard mode, all conjugations, N5, N4).
- New conjugation forms (volitional, ながら, ば, たら, causative) and のに/ので: tokenization assumptions not checked on real SudachiPy yet — some may find few or no sentences.
- make_exercises refactored: generate() / generate_topic() reusable by fill_reserve and the server.

## 2026-09-28 — Anki without Anki, JLPT, deeper chat, autostart

- Reserve fill from the app worked: ます, は/が, を/が +15 each, 0 dropped, ~77 s per topic. Suspicious: Qwen still drops nothing; は/が sentences like 私は来週出発します may accept が too.
- `anki_db.py` + new `anki_sync.py`: reads a copy of collection.anki2 (Anki closed or open), detects note types of any deck (data/anki.json), exports lexicon (forms, reading, meaning, JLPT level from the deck path or tags), grammar points (FJSD-Grammar: 644 points), kanji with on/kun'yomi. AnkiConnect kept as a fallback.
- `jlpt_data.py`: open JLPT vocabulary lists (open-anki-jlpt-decks, MIT, from tanos.co.uk CC BY) into the lexicon.
- `jlpt_questions.py`: 漢字読み (rule-based wrong readings), 表記 (kanji sharing an on'yomi), 文脈規定 and 文法形式 (LLM-checked), 並べ替え ★ (sentence pieces). `conjugate.py` for verb-form choices; the bank now stores the conjugation type (rebuild).
- JLPT tab: practice (multiple choice in the session, keys 1–4) and timed mock exams with score per section and history.
- Chat: `knowledge.py` injects references (Anki grammar notes, programme notes, lexicon, Tatoeba sentences) and shows which were used; modes Prof / Conversation (7 situations) / Quiz.
- `install_autostart.py` + startup maintenance (Anki sync once a day, reserve and JLPT top-up when Ollama answers), settings in the app.
- Tested with a simulated Anki collection (new and old formats), SudachiPy, Ollama and headless Chromium. To check on the real machine: FJSD field parsing, JLPT question quality (especially 並べ替え and 文脈規定), conjugation types from SudachiPy.

## 2026-09-28 — Review of the generated questions on the real data

First look at the real reserve (50 JLPT N4 questions, 40 programme exercises), done by Claude through the app:
- Qwen's check had kept everything (50/50), including clearly ambiguous questions.
- は/が: about half the exercises accepted both answers without context (我々のチーム＿試合に勝った).
- JLPT: the 50 questions came from ~10 sentences, each used for the 5 types, so one question gave away another's answer.
- 並べ替え: ~6/10 had several correct orders (塩を / ポップコーンに, 好きなものを / どれでも, 今日は…).
- 漢字読み: fake-looking wrong readings (ちっから, がっつ); 表記: random rare kanji (梨用, 痔); raw Anki meanings (« Common noun; Usually written using kana alone… »); 事 asked as a kanji reading.
- FJSD-Radical notes overwrote the kanji notes in kanji.json (力: no readings), FJSD-Kana were read as words.

Fixes, then generate → review → fix loops on the real bank (N5, N4, N3) until the batches looked right:
- One sentence per JLPT question; words usually written in kana skipped (Anki tag); counters (3月) skipped; the answer must not appear elsewhere in the sentence.
- Wrong readings from the split of the word into its kanji (交通 → 交/こう + 通/つう): another on'yomi of the kanji (on'yomi compounds only), long ↔ short vowel (no う added to a kun'yomi), voicing (never ぢ/づ), っ ↔ つ/く from the kanji's real reading, ゅ ↔ ゆ; one wrong answer per family.
- Wrong spellings: kanji with the same on'yomi, level N5–N3 or known, never forming a real word.
- 文法形式: particle pairs that are often both right never offered together; に/と and に/から pairs dropped with 会う / 習う-type verbs; を/が never together; conjugations: て/たら/ば not offered together outside て + auxiliary; no verb-form question at the end of a sentence (教えて / 教えよう / 教えます all fit); verbs the analyzer cut wrongly (くびっ|たけ) and sentences with filler tokens (あ, う) skipped.
- 並べ替え: at most one movable piece (case particle, adverb, bare noun, clause, 〜か…); no topic (は, も, なら, たり); no two adjacent modifiers of the same noun (彼女の / 新しい, きれいな / 静かな, この / その); no dialogues, punctuation or one-kana pieces; longer sentences allowed (+8 words); translation shown. Yield is low (≈10 N4 questions in the whole bank) but they have a single answer.
- Programme particles: は/が only where the grammar decides (が in a subordinate clause, 誰が, existence after a place; は before a question word); は/も decided by the translation (« aussi »); に/へ both accepted with movement verbs; を/が both accepted with たい and potential forms; や also accepts と.
- `review.py`: revalidate (at every startup: removes what the current rules would not generate, fixes accepted answers), export, reject, import; reviewed batches dropped in `data/reviews/` are applied at startup. Rejected keys are never generated again (table `rejected`).
- anki_sync: FJSD-Radical and FJSD-Kana ignored; a kanji note without readings no longer overwrites one with readings; the sync runs again at startup when data/anki.json changed.
- On a copy of the real reserve: 64 exercises retired (47 old-generator JLPT, 14 は/が, 3 kana words); Claude's manual review of the new batch rejected 5 more (3 に/で where both fit, 2 odd sentences).

## 2026-09-28 — Undo, « je ne maîtrise pas », reviews by hand

- Each answer keeps the review schedule it replaced (`reviews.prev`): « Annuler ma réponse » / Ctrl+Z deletes the answer and restores it (or goes back to the previous exercise); « En fait je ne maîtrise pas » replaces a right answer by a wrong one.
- `schedule.suspended`: « Ne plus proposer » and Progrès → Révisions (list, filter, review today, suspend, reactivate, report); « ⚑ Signaler une erreur » retires the exercise (table `rejected`, reason « signalé… ») — these reports feed the next quality review.
- Tested in headless Chromium on a copy of the real database (undo after right / wrong answers, back to the previous exercise, suspend, report, list, search, adding a never-seen exercise to today's reviews).

## 2026-09-28 — English version

- `language` setting (fr / en), selector in the top bar; the server writes it into `<html lang>`.
- `web/i18n.js`: every interface text in French and English (`t()`, `tn()` for plurals, `data-i18n*` attributes in index.html).
- Topic titles stay the French keys in the database; `curriculum.title()` / `note()` give the English ones (`title_en`, `note_en`), JLPT labels too.
- Exercises: `translation_en`, `hint_en`, `explanation_en` saved by the generators (the LLM writes both languages); the server localizes what it sends (`localize()`), falling back to the Tatoeba bank for older exercises. French-only explanations are hidden in English.
- Tutor: English prompts, situations, student context and references (Tatoeba sentences with their English translation).
- `build_bank.py` now keeps the English translations by default (the bank must be rebuilt once); generation requires a translation in the interface language.
- Tested in headless Chromium: switching languages, session, progress, JLPT, chat; no French left in the English interface except existing chat history.
