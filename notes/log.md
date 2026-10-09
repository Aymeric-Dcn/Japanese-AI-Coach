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
- Qwen's check (文脈規定 and 文法形式) had kept every question it saw, including clearly ambiguous ones.
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

## 2026-09-28 — Shared bank, README

- `bank_sync.py`: separate repository Japanese-AI-Coach-bank (CC BY-SA 4.0) with `manifest.json` (sha256 per file), `exercises/<topic>.jsonl`, `rejected.jsonl`, `inbox/`. `pull` at startup adds new exercises (origin « bank ») and retires rejected keys, without touching progress; `contribute` sends local exercises (folder or GitHub API); `import-inbox` and `publish` for the maintainer. Only exercise content is shared (`new_words`, which depends on the student's Anki, is stripped).
- Review loop: exercises carry `review` once approved (`review.py` batches: `approve`, `approve_all`, `export --unreviewed`); only approved exercises are published.
- Generation now requires both a French and an English translation (39,278 sentences), so every exercise works in both languages. Two 並べ替え made in English mode without a French translation were rejected, one of them also mis-tokenized (どこかなぞめいた → どこかな / ぞめいた).
- Tested end to end on copies: publish 131 exercises → a fresh database pulls them (progress untouched) → it generates and contributes 4 → the maintainer imports, rejects 1, approves 3, publishes v2 → the friend's pull retires the rejected one.
- README rewritten as a project page (screenshots taken in headless Chromium on a copy of the real database, EN and FR); detailed documentation moved to `docs/guide.md` / `docs/guide.fr.md`.

## 2026-09-28 — Windows app for friends (no Anki, no GPU)

- Welcome screen on first start: language, starting level (N5, or N4 with the N5 topics marked as known), Anki (detected or not), and the local model explained (Ollama, ≈ 9 GB, GPU with 8–12 GB, stays on the computer). Nothing runs before it is answered; then the startup job pulls the shared bank.
- Without a local model: no 15-minute wait for Ollama at startup, the « generate » buttons are hidden, the Teacher tab explains what is missing, and topics with no exercise in the reserve are skipped so the daily programme always has something to offer.
- `build_exe.py` (PyInstaller): one-file, no console; data in %LOCALAPPDATA%\JapaneseCoach; a second double-click opens the running app; ⏻ closes it. SudachiPy and the sentence bank are not included (only needed to generate).
- Tested by simulating the packaged mode (sys.frozen, _MEIPASS) on an empty profile: welcome screen FR → EN, level N4, bank pulled (134 exercises), daily programme, Teacher tab message, quit. The real .exe must be built on Windows.

## 2026-09-28 — Cloud teacher (Claude / ChatGPT)

- `llm.py` routes models named `anthropic:<id>` / `openai:<id>` to the Messages / Chat Completions APIs (streaming, JSON answers via the schema in the prompt); keys from settings or `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`. Defaults: `claude-haiku-4-5-20251001`, `gpt-5.4-mini` (to check against OpenAI's current list).
- Progrès → « Le prof (modèle d'IA) »: provider, model, key. The key is kept in `data/settings.json` and never returned to the page (only « key set »). Only the chat uses it; exercise generation stays local, so the bank keeps one source.
- Tested against fake Anthropic / OpenAI servers: streamed answer, JSON answer, 401 and missing key shown as a readable error, status « Prof : claude-haiku… », back to local shows « Ollama éteint ».

## 2026-09-28 — Review 5: 227 generated exercises, bank v2

- Generated on the PC (`fill_reserve.py --all`, `jlpt_questions.py --level N5`, qwen3:14b): 187 exercises and 40 JLPT N5 questions. Qwen « checked » and kept all 227.
- Review: 14 rejected (6 %), 213 approved. Rejected: cues that mislead (いけない as the negative of いける, ありえない cut in two, かけば given as かける), verbs that only look causative (済ませる, 知らせる), 生まれながら (« by birth », not simultaneity), a haiku in と / や, an ungrammatical Tatoeba sentence, and four JLPT questions with a second right answer (小さい手 / 本, 八日に / 外に出たくない, アメリカに / から来ました, 兄 / 学校行きたくない). One answer fixed: 以内へ was accepted.
- Qwen's hints and explanations were almost all generic or wrong (« ajoutez ない à la forme de base » for 悩まさない, « En français, に est souvent utilisé… », hints quoting the answer): all 213 rewritten FR + EN.
- Rules added so the next batches need less review:
  - conjugations: the hint and the « how it is built » line come from `conjugate.describe()` (verb class, row change, て-form chart); Qwen only writes why the form is used. ながら added to the conjugator; godan compounds (生き返る, 立ち入る…) no longer taken for ichidan.
  - particles: hints that quote the answer or talk about « French » are dropped; the prompt asks for the role of the word and why the other choices are wrong.
  - に / へ: after a time (以内, ５時, 前…) only に.
  - Volitional: SudachiPy keeps 行こう in one token, so the topic had 0 candidates; now 306. のに / ので: split as の + で / に, 0 candidates before; now 64, kept only when the translation says « although » or « because ».
  - JLPT 文法形式: no volitional or verb before と思う / と言う (every finite form fits), no に / へ / まで distractor for から with a movement verb, no を / で pair after a language (英語を / で話す).
- Bank v2: 338 exercises in 25 files, 92 rejected keys.

## 2026-09-28 — Review 6: volitional and のに / ので

- The two topics that had 0 candidates produced 30 exercises (qwen3:14b kept all 30). 1 rejected: 取り除けよう (rare verb 取り除ける, and the reading given was wrong). 29 approved.
- The rule-written hints and « how it is built » lines were right on all 15 volitional items. Qwen's own parts were still generic, and two のに / ので explanations said « は marks the topic… 寒かった is the topic »: the « は = topic » reminder in the prompt made it talk about は where it had nothing to do. It is now only added when は is one of the choices.
- のに / ので hints now come from a rule (« is the first part the cause of the second, or does the second happen in spite of it? »): Qwen's hints named the answer (« a word that marks a cause »). 〜ようとする and 〜ようと思う are explained by rules after the volitional.
- `compare_models.py`: the same candidates (fixed seed) checked and explained by several models, written to data/compare/ for review, before switching the default model.
- Bank v3: 367 exercises, 93 rejected keys.

## 2026-09-28 — qwen3:14b vs qwen3:30b-a3b (`compare_models.py`, 33 items)

- Kept: 33/33 vs 32/33. The 30B dropped 褒美をやろう because the French translation is wrong (« Tu devrais être récompensé »): right, the 14B missed it. Both kept 「（　　）だった。」 (今朝 / 問題 だった fit too): JLPT vocab questions now need at least two content words besides the blank.
- Explanations: both still wrong on the same points (が « marks the time » in 亡くなる前に; に / へ: both say へ (or に) is impossible after 行く / 帰る, although the two are right). The 30B is more concrete on the wrong choices (it says what 漢字だった or 四日 would mean), but it switched to Japanese in 5 of 33 explanations (« 他の助詞は文脈に合いません », « はは主題を示す助詞で… »): unusable as is for a French student.
- Time: 18 s vs 26 s per item, but the script alternated the two models and Ollama reloaded them from disk at each switch (the SSD at 100 %): the script now runs one model at a time and does not count the first call.
- Conclusion: no reason to switch the local default to the 30B. The explanations need review whatever the local model; the next test is a cloud model (Claude Haiku / Sonnet) on the same seed.
- Scripts run from the command line now read the API key saved in the app (data/settings.json).

## 2026-09-28 — The .exe opens in its own window

- Before: the .exe opened a tab on http://localhost:8000 in the default browser, and kept running after the tab was closed (only ⏻ stopped it).
- Now it opens Edge (present on every Windows 10/11) or Chrome in app mode (`--app`, a profile of its own in %LOCALAPPDATA%\JapaneseCoach\window): no address bar, no tabs, its own taskbar entry. Without Edge or Chrome, the browser as before. `python server.py --window` does the same from the source.
- The app stops when its window is closed: the page pings the server every 20 s and sends a beacon when it goes away (pagehide); the server stops 10 s after the beacon unless the page pings again (a reload does), or after 5 minutes without any sign of the page.
- Tested with Chromium: a reload keeps the server running, leaving the page stops it after ~10 s. The Edge window itself can only be tested on Windows.

## 2026-09-29 — Word order, relative clauses, 前に / 後で, ても

- **Word order** (`word_order.py`, topic « Ordre des mots », N5): the translation is shown, the sentence is cut into pieces (a word with its particles) and shuffled; the student clicks them in order. Any order with the predicate last is accepted (and a first でも / はい stays first): the pieces carry their particle, so their order is free; when the answer differs from the sentence, the most usual order is shown. That rule only holds for simple sentences, so the generator keeps one predicate at the end and pieces that can move, and glues what cannot: 私の / この / 大きい to their noun, とても to its adjective, もう + すぐ, 小さく + 見える, 手に + 取る (set phrases with a body word). Left out: relative clauses (昨日 in 昨日買った本 would change meaning if moved), 妻を見舞いに行く (を belongs to 見舞い), 耳にする, 一か八か, 六ヶ月に一度.
- **Relative clauses** (`clauses.py`, N5): « は ou が » only where the grammar decides: が of a relative clause when the sentence already has a topic before it (これは私が書いた手紙です), の accepted too; with adjectives (青が一番美しい色だ) it is often a sentence of its own, so only verbs. « Verbe devant le nom »: past, negative, ている forms (the dictionary form would be the cue copied).
- **前に / 後で and ても** (N4): 行く前に (dictionary form), 食べた後で (past), 降っても; left out: 〜てもいい / よろしい (permission), にしても, どうしても, なんと言っても, 思ってもみない, とっても (= とても).
- All these hints and explanations are written by rules: no model needed, and nothing to correct afterwards.
- Generated here and reviewed: 105 items, 12 rejected (a wrong French translation, 気がする and 青が…色だ that are not relative clauses, contrastive は possible in 意味がわからない, ばかげた, しなければならない, duplicates, 〜てもご迷惑では = permission, 六ヶ月に一度, 三年間日記 cut as one noun). The rules were tightened for each.
- Found on the way: the reserve check read only the French translation for のに / ので and retired good exercises at startup (10 in the copy of the PC's database). Fixed, and those retirements are undone: the next bank pull brings them back.
- An app pulls only the kinds of exercise it can show; a file with a newer kind is read again after the app is updated.
- Bank v4: 460 exercises, 105 rejected keys.

## 2026-09-29 — Updates and welcome wizard (v0.2.0)

- `updater.py`: at startup the Windows app asks GitHub for the latest release (`VERSION` = 0.2.0 vs the tag). Modes: « auto » (downloaded in the background, installed when the app closes), « notify » (banner + « Update » button, default), « off ». The new .exe is downloaded to %LOCALAPPDATA%\JapaneseCoach\update, its size checked; a small hidden script waits until the running .exe has stopped, swaps it, and starts it again. Progress is elsewhere, so nothing is lost; downloaded by the app itself, the file carries no « from the Internet » mark, so no SmartScreen warning again.
- The welcome screen is now a 5-step wizard: language and level; Anki (found or not, what is read: word / kanji / grammar notes of any deck); the teacher (none, local, Claude or ChatGPT with the key typed right there); updates; summary. Progress → « The app » shows the version, the update mode and « Check now ».
- Tested with a fake release server: check, banner, download with size check, wizard choices saved (level N4, Claude + key, updates auto). The swap of the .exe itself only runs on Windows.

## 2026-10-04 — Click or drag the answer (v0.2.1)

- When the possible answers are shown (particles, « Mode difficile » off), they are buttons: a click puts the answer in the blank and checks it, and they can also be dragged onto the blank. Typing still works, and « Mode difficile » still hides them. A wrong pick can be followed by another one, as with typing.
- `updater.VERSION` = 0.2.1: the first release that installed apps (v0.2.0) should offer by themselves.

## 2026-10-09 — Phone and Raspberry Pi

- Everything here is opt-in: by default the app still listens on 127.0.0.1 only and the `.exe` is unchanged.
- `server.py --host` (default 127.0.0.1; prints a warning when it is not local) and `--ollama` / the `ollama_url` setting / `JAPANESE_COACH_OLLAMA`: a Pi can use the PC's Ollama through Tailscale (`llm.set_ollama_url` accepts « my-pc », « 100.x.y.z » or a full URL).
- The startup maintenance (bank pull, reserve check…) runs again every 24 h, so an app that stays on gets the new exercises of the shared bank without a restart.
- Phone layout (≤ 600 px): one line « ● Japanese Coach … FR », the four tabs across the width, no service status, 16 px inputs (no zoom on iPhone), safe areas; the programme table becomes one block per topic with labelled numbers. Checked on a Pixel 7 viewport: no horizontal scroll, tiles work by tap.
- PWA: `web/manifest.webmanifest`, icons 192 / 512 / apple-touch (日 on the app red), theme-color: « Add to Home screen » opens it full screen. Mimetypes set in the server (Windows can map them wrongly).
- `deploy/install-pi.sh` writes and starts a systemd service; `docs/raspberry-pi.md` (+ .fr): Python check, clone, copying `data/` from the PC (not bank.db), `tailscale serve --bg 8000` for HTTPS, the teacher with a cloud key or the PC's Ollama (`OLLAMA_HOST=0.0.0.0`).
- The server runs without SudachiPy (checked with Python 3.8 and 3.9 in an empty environment).

## 2026-10-09 — English translations without the Tatoeba bank; « program »

- In English, exercises made before both translations were stored showed the French one when `data/bank.db` is missing (the `.exe` and the Raspberry Pi do not have it). Now:
  - the reserve check (`review.add_translations`, at every start where `bank.db` exists) stores the French and English translations in those exercises;
  - `bank_sync.pull` completes exercises already in the reserve with the texts the bank has and they lack (`translation`, `translation_en`, `hint_en`, `explanation_en`, never overwritten: `store.fill_missing`). Every bank file is read again once (`FILL_VERSION`) so apps that already downloaded it get them.
- English interface and docs: « program » instead of « programme ».
