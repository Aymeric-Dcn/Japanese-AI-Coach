"""
Shared helpers: text normalization, output paths and the interactive HTML exercise sheet.

A sheet is a dict with this shape (lesson and vocabulary are optional):

    {
      "title": str,
      "lesson": {"introduction": str,
                 "points": [{"rule": str, "examples": [{"jp": str, "reading": str, "translation": str}]}]},
      "vocabulary": [{"word": str, "reading": str, "meaning": str}],
      "exercises": [{
          "sentence": str,           # contains exactly one BLANK
          "answers": [str],          # accepted answers, the first one is shown as the solution
          "hint": str, "translation": str, "explanation": str,
          # optional:
          "full_sentence": str, "reading": str, "show_translation": bool,
          "source": str, "source_url": str, "new_words": [str],
          "cue": str                 # conjugation exercises: the verb's dictionary form, shown after the blank
      }],
      "meta": {"topic": str, "level": str, "model": str, "date": str, "allowed_answers": [str]}
    }
"""

import datetime
import json
import re
import unicodedata
from pathlib import Path

BLANK = "___"
OUTPUT_DIR = Path("sheets")


def normalize(text: str) -> str:
    """Width-insensitive, whitespace-free form used to compare answers."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text)))


def split_list(text: str) -> list:
    """« に,で » / « に、で » / « に で » → ["に", "で"]"""
    return [x.strip() for x in re.split(r"[,，、/\s]+", text or "") if x.strip()]


def output_base(name: str) -> Path:
    """sheets/2026-09-27_203015_<slug> (without extension)."""
    slug = re.sub(r"[^\w]+", "-", name.lower()).strip("-")[:40] or "sheet"
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    OUTPUT_DIR.mkdir(exist_ok=True)
    return OUTPUT_DIR / f"{stamp}_{slug}"


def save_sheet(sheet: dict, name: str) -> Path:
    """Writes the sheet as JSON + HTML and returns the HTML path."""
    base = output_base(name)
    base.with_suffix(".json").write_text(json.dumps(sheet, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = base.with_suffix(".html")
    write_html(sheet, html_path)
    return html_path


def write_html(sheet: dict, path: Path) -> None:
    data = json.dumps(sheet, ensure_ascii=False).replace("</", "<\\/")
    title = (sheet.get("title", "Japanese sheet")
             .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    page = HTML_TEMPLATE.replace("/*__DATA__*/", data).replace("__TITLE__", title)
    path.write_text(page, encoding="utf-8")


# The page's interface text is in French (the learner's language); everything else is English.
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#faf8f5;--card:#fff;--text:#1f1d1a;--muted:#6b665e;--border:#e6e1d9;--accent:#b8323a;
--ok:#2f7d4f;--ok-bg:#e8f4ec;--ko:#b8323a;--ko-bg:#fbeaea;--hint-bg:#fff7e0}
@media (prefers-color-scheme: dark){:root{--bg:#171614;--card:#211f1c;--text:#ece8e1;--muted:#a39d93;
--border:#35322d;--accent:#e06a70;--ok:#6cc58e;--ok-bg:#1c2e23;--ko:#e98088;--ko-bg:#35201f;--hint-bg:#2e2a1d}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);line-height:1.6;
font-family:system-ui,-apple-system,"Segoe UI","Hiragino Sans","Yu Gothic UI",Meiryo,"Noto Sans JP",sans-serif}
main{max-width:760px;margin:0 auto;padding:32px 16px 80px}
.meta{color:var(--muted);font-size:.9rem}
h1{font-size:1.8rem;margin:.1em 0 .3em}
h2{font-size:1.2rem;margin:2.2rem 0 .6rem;border-bottom:2px solid var(--accent);display:inline-block;padding-bottom:2px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px 18px;margin:12px 0}
.rule{font-weight:600;margin-bottom:.4rem}
.example{margin:.6rem 0 .2rem}
.jp{font-size:1.25rem}
.reading{color:var(--muted);font-size:.9rem}
.tr{color:var(--muted);font-style:italic;font-size:.95rem}
body.hide-readings .reading{display:none}
table{width:100%;border-collapse:collapse}
td,th{padding:8px 6px;border-bottom:1px solid var(--border);text-align:left}
th{color:var(--muted);font-weight:500;font-size:.85rem}
td.jp{font-size:1.15rem}
.toolbar{position:sticky;top:0;background:var(--bg);padding:10px 0;display:flex;gap:8px;flex-wrap:wrap;
align-items:center;z-index:5;border-bottom:1px solid var(--border)}
.score{margin-left:auto;font-weight:600}
button{font:inherit;font-size:.9rem;padding:6px 12px;border-radius:8px;border:1px solid var(--border);
background:var(--card);color:var(--text);cursor:pointer}
button:hover{border-color:var(--muted)}
button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.num{color:var(--muted);font-size:.85rem}
.sentence{font-size:1.35rem;margin:.2rem 0 .7rem;line-height:2.2}
.sentence input{font:inherit;font-size:1.2rem;width:6em;padding:0 8px;border:none;border-bottom:2px solid var(--accent);
background:transparent;color:var(--text);text-align:center;outline:none}
.sentence input:focus{background:var(--hint-bg)}
.cue{color:var(--muted);font-size:1rem}
.exo.ok .sentence input{border-color:var(--ok);color:var(--ok)}
.exo.ko .sentence input{border-color:var(--ko)}
.exo > .reading, .exo > .tr{margin:-.4rem 0 .6rem}
.actions{display:flex;gap:8px;flex-wrap:wrap}
.hint{background:var(--hint-bg);padding:8px 12px;border-radius:8px;margin-top:10px}
.feedback{margin-top:10px;padding:10px 12px;border-radius:8px}
.exo.ok .feedback{background:var(--ok-bg)}
.exo.ko .feedback{background:var(--ko-bg)}
.source{color:var(--muted);font-size:.8rem}
.choices{margin:.4rem 0 0}
.choices span{display:inline-block;font-size:1.2rem;padding:0 10px;margin:0 4px;border:1px solid var(--border);
border-radius:6px;background:var(--card)}
[hidden]{display:none!important}
.end{text-align:center;font-size:1.1rem;margin-top:24px}
</style>
</head>
<body>
<main id="app"></main>
<script>
const UI = {
  lesson: "Cours", vocabulary: "Vocabulaire", exercises: "Exercices",
  word: "Mot", reading: "Lecture", meaning: "Sens", exercise: "Exercice",
  choices: "Réponses possibles :", hideReadings: "Masquer les lectures", showReadings: "Afficher les lectures",
  checkAll: "Tout vérifier", reset: "Recommencer", check: "Vérifier", hint: "Indice", showAnswer: "Voir la réponse",
  correct: "✓ <strong>Correct !</strong>", wrong: "✗ Pas tout à fait. Réessaie, demande un indice ou affiche la réponse.",
  answer: "Réponse :", accepted: "Réponses acceptées :", newWords: "Nouveau :",
  score: (ok, n, done) => `${ok} / ${n} du premier coup · ${done}/${n} terminés`,
  finished: (ok, n) => `Terminé ! ${ok} / ${n} du premier coup.`,
};
const DATA = /*__DATA__*/;
const BLANK = "___";
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const norm = s => String(s).normalize("NFKC").replace(/[\s。、．，.,!！?？「」]/g, "");
const app = document.getElementById("app");
const meta = DATA.meta || {};

let html = `<p class="meta">${[meta.level, meta.date, meta.model].filter(Boolean).map(esc).join(" · ")}</p>
<h1>${esc(DATA.title)}</h1>`;

const lesson = DATA.lesson;
if (lesson && (lesson.introduction || (lesson.points || []).length)) {
  html += `<h2>${UI.lesson}</h2>`;
  if (lesson.introduction) html += `<div class="card"><p>${esc(lesson.introduction)}</p></div>`;
  for (const p of lesson.points || []) {
    html += `<div class="card"><div class="rule">${esc(p.rule)}</div>`;
    for (const e of p.examples || []) {
      html += `<div class="example"><div class="jp" lang="ja">${esc(e.jp)}</div>
        <div class="reading" lang="ja">${esc(e.reading)}</div><div class="tr">${esc(e.translation)}</div></div>`;
    }
    html += `</div>`;
  }
}

if (DATA.vocabulary && DATA.vocabulary.length) {
  html += `<h2>${UI.vocabulary}</h2><div class="card"><table><tr><th>${UI.word}</th><th class="reading">${UI.reading}</th><th>${UI.meaning}</th></tr>`;
  for (const v of DATA.vocabulary) {
    html += `<tr><td class="jp" lang="ja">${esc(v.word)}</td><td class="reading" lang="ja">${esc(v.reading)}</td><td>${esc(v.meaning)}</td></tr>`;
  }
  html += `</table></div>`;
}

html += `<h2>${UI.exercises}</h2>`;
if (meta.allowed_answers && meta.allowed_answers.length) {
  html += `<p class="choices">${UI.choices} ${meta.allowed_answers.map(r => `<span lang="ja">${esc(r)}</span>`).join("")}</p>`;
}
html += `
<div class="toolbar">
  <button id="btn-readings">${UI.hideReadings}</button>
  <button id="btn-check-all">${UI.checkAll}</button>
  <button id="btn-reset">${UI.reset}</button>
  <span class="score" id="score"></span>
</div>`;

DATA.exercises.forEach((ex, i) => {
  const [before, after] = ex.sentence.split(BLANK);
  html += `<div class="card exo" id="exo-${i}">
    <div class="num">${UI.exercise} ${i + 1}</div>
    <div class="sentence" lang="ja">${esc(before)}<input lang="ja" autocomplete="off" spellcheck="false" data-i="${i}" aria-label="${UI.exercise} ${i + 1}" style="width:${Math.max(4, ex.answers[0].length + 2)}em">${ex.cue ? `<span class="cue">（${esc(ex.cue)}）</span>` : ""}${esc(after)}</div>
    ${ex.reading ? `<div class="reading" lang="ja">${esc(ex.reading)}</div>` : ""}
    ${ex.show_translation ? `<div class="tr">${esc(ex.translation)}</div>` : ""}
    ${(ex.new_words || []).length ? `<div class="tr">${UI.newWords} <span lang="ja">${ex.new_words.map(esc).join("、")}</span></div>` : ""}
    <div class="actions">
      <button class="primary" data-action="check" data-i="${i}">${UI.check}</button>
      <button data-action="hint" data-i="${i}"${ex.hint ? "" : " hidden"}>${UI.hint}</button>
      <button data-action="answer" data-i="${i}" hidden>${UI.showAnswer}</button>
    </div>
    <div class="hint" hidden>💡 ${esc(ex.hint)}</div>
    <div class="feedback" hidden></div>
  </div>`;
});
html += `<p class="end" id="end" hidden></p>`;
app.innerHTML = html;
document.title = DATA.title;

const state = DATA.exercises.map(() => ({ first: null, solved: false }));
const exo = i => document.getElementById("exo-" + i);
const field = i => exo(i).querySelector("input");

function solution(i, message) {
  const ex = DATA.exercises[i];
  const others = ex.answers.length > 1 ? `<br>${UI.accepted} <span lang="ja">${ex.answers.map(esc).join(" / ")}</span>` : "";
  const tr = ex.translation && !ex.show_translation ? `<br><span class="tr">${esc(ex.translation)}</span>` : "";
  const expl = ex.explanation ? `<br>${esc(ex.explanation)}` : "";
  const src = ex.source_url ? `<br><a class="source" href="${esc(ex.source_url)}" target="_blank" rel="noopener">${esc(ex.source || "source")}</a>` : "";
  return `${message}${others}${tr}${expl}${src}`;
}

function check(i) {
  const st = state[i];
  if (st.solved) return true;
  const ex = DATA.exercises[i], box = exo(i), value = field(i).value;
  if (!norm(value)) { field(i).focus(); return false; }
  const ok = ex.answers.some(a => norm(a) === norm(value));
  if (st.first === null) st.first = ok;
  box.classList.toggle("ok", ok);
  box.classList.toggle("ko", !ok);
  const fb = box.querySelector(".feedback");
  fb.hidden = false;
  if (ok) {
    st.solved = true;
    field(i).readOnly = true;
    box.querySelector('[data-action="answer"]').hidden = true;
    fb.innerHTML = solution(i, UI.correct);
  } else {
    box.querySelector('[data-action="answer"]').hidden = false;
    fb.innerHTML = UI.wrong;
  }
  updateScore();
  return ok;
}

function showAnswer(i) {
  const st = state[i], box = exo(i), ex = DATA.exercises[i];
  if (st.first === null) st.first = false;
  st.solved = true;
  field(i).value = ex.answers[0];
  field(i).readOnly = true;
  box.classList.remove("ok"); box.classList.add("ko");
  box.querySelector('[data-action="answer"]').hidden = true;
  const fb = box.querySelector(".feedback");
  fb.hidden = false;
  fb.innerHTML = solution(i, `${UI.answer} <strong lang="ja">${esc(ex.answers[0])}</strong>`);
  updateScore();
}

function updateScore() {
  const n = state.length;
  const ok = state.filter(s => s.first === true).length;
  const done = state.filter(s => s.solved).length;
  document.getElementById("score").textContent = UI.score(ok, n, done);
  const end = document.getElementById("end");
  end.hidden = done < n;
  if (done === n) end.textContent = UI.finished(ok, n);
}

function focusNext(i) {
  for (let j = i + 1; j < state.length; j++) if (!state[j].solved) { field(j).focus(); return; }
}

app.addEventListener("click", e => {
  const b = e.target.closest("button[data-action]");
  if (!b) return;
  const i = +b.dataset.i;
  if (b.dataset.action === "check" && check(i)) focusNext(i);
  if (b.dataset.action === "hint") exo(i).querySelector(".hint").hidden = false;
  if (b.dataset.action === "answer") showAnswer(i);
});

app.addEventListener("keydown", e => {
  if (e.target.tagName !== "INPUT" || e.key !== "Enter") return;
  if (e.isComposing || e.keyCode === 229) return; // Enter is confirming Japanese IME input
  e.preventDefault();
  const i = +e.target.dataset.i;
  if (check(i)) focusNext(i);
});

document.getElementById("btn-readings").onclick = e => {
  const hidden = document.body.classList.toggle("hide-readings");
  e.target.textContent = hidden ? UI.showReadings : UI.hideReadings;
};
document.getElementById("btn-check-all").onclick = () => {
  state.forEach((s, i) => { if (!s.solved && norm(field(i).value)) check(i); });
};
document.getElementById("btn-reset").onclick = () => {
  state.forEach((s, i) => {
    s.first = null; s.solved = false;
    const box = exo(i);
    box.classList.remove("ok", "ko");
    field(i).value = ""; field(i).readOnly = false;
    box.querySelector(".feedback").hidden = true;
    box.querySelector(".hint").hidden = true;
    box.querySelector('[data-action="answer"]').hidden = true;
  });
  updateScore();
  field(0).focus();
};

updateScore();
</script>
</body>
</html>
"""
