// Japanese Coach — interface (session, chat with the tutor, progress).
// Talks to server.py through /api/…; interface texts are in i18n.js (t(), tn()).
"use strict";

const BLANK = "___";
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const norm = s => String(s).normalize("NFKC").replace(/[\s。、．，.,!！?？「」]/g, "");

function toast(text, ms = 4000) {
  const t = $("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, ms);
}

async function api(path, body) {
  const opts = body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function store(key, value) {  // small per-browser preferences; the app works without them
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (e) { return null; }
}

// ======================================================================
// Tabs and status
// ======================================================================

function showTab(name) {
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("active", p.id === "tab-" + name));
  if (name === "progress") loadProgress();
  if (name === "jlpt") loadJlpt();
  if (name === "chat") { loadChat(); $("chat-input").focus(); }
}
document.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));

const STATUS = {data: null};

async function loadStatus() {
  try {
    const s = await api("/api/status");
    STATUS.data = s;
    $("btn-quit").hidden = !s.packaged;
    const noModel = s.local_model === false && !s.ollama;   // generating needs the local model
    $("btn-fill").hidden = noModel;
    $("btn-jlpt-fill").hidden = noModel;
    $("chat-off").hidden = !!s.chat_ready;
    $("chat-off").textContent = t("chat_off", {model: s.model});
    const item = (ok, on, off) => `<span class="${ok ? "on" : "off"}">${ok ? on : off}</span>`;
    const cloud = s.chat_model && s.chat_model.includes(":") && /^(anthropic|openai):/.test(s.chat_model);
    $("status").innerHTML =
      (cloud ? item(s.chat_ready, t("teacher_on_cloud", {model: esc(s.chat_model.split(":")[1])}), t("teacher_on_cloud", {model: esc(s.chat_model.split(":")[1])}) + " ✗") :
       s.local_model === false && !s.ollama ? "" : item(s.ollama && s.model_installed, t("teacher_on", {model: esc(s.model)}),
           s.ollama ? t("model_missing", {model: esc(s.model)}) : t("ollama_off"))) +
      (s.anki_found || s.anki_sync ? item(s.anki_sync, t("anki_on"), t("anki_off")) : "");
    return s;
  } catch (e) {
    $("status").innerHTML = `<span class="off">${t("server_down")}</span>`;
    return null;
  }
}

// ======================================================================
// Session
// ======================================================================

const S = {queue: [], pos: 0, done: 0, firstTry: 0, current: null, solved: false, lastStats: null};

function renderSummary(stats) {
  S.lastStats = stats;
  const pct = stats.today.done ? Math.round(100 * stats.today.correct / stats.today.done) : 0;
  $("summary").innerHTML = [
    `<span class="pill">${t("pill_due", {n: stats.due_now})}</span>`,
    `<span class="pill">${t("pill_unseen", {n: stats.unseen})}</span>`,
    `<span class="pill">${t("pill_today", {n: stats.today.done})}${stats.today.done ? t("pill_today_pct", {pct}) : ""}</span>`,
    stats.day_streak ? `<span class="pill">${tn("pill_streak", stats.day_streak)}</span>` : "",
  ].join("");
}

const P = {mode: store("mode") || "daily", topics: [], picked: new Set(JSON.parse(store("picked") || "[]"))};
const STATE_LABEL = {passed: t("state_passed"), current: t("state_current"), locked: t("state_locked"), custom: t("state_custom")};
const label = topic => (P.topics.find(x => x.title === topic) || {}).label || topic;  // topic title in the interface language

function setMode(mode) {
  P.mode = mode;
  store("mode", mode);
  document.querySelectorAll(".seg[data-mode]").forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
  $("mode-daily").hidden = mode !== "daily";
  $("mode-practice").hidden = mode !== "practice";
  updateStartButton();
}
document.querySelectorAll(".seg[data-mode]").forEach(b => b.addEventListener("click", () => setMode(b.dataset.mode)));

function updateStartButton() {
  const reserve = P.topics.reduce((n, t) => n + t.total, 0);
  $("btn-start").disabled = !reserve || (P.mode === "practice" && !P.picked.size);
}

function renderPicker() {
  const levels = {};
  for (const t of P.topics) {
    if (!t.total) continue;  // nothing to practise yet
    (levels[t.level || t_("others")] = levels[t.level || t_("others")] || []).push(t);
  }
  const html = Object.entries(levels).map(([level, list]) => `<h4>${esc(level)}</h4>` + list.map(t =>
    `<label><input type="checkbox" value="${esc(t.title)}"${P.picked.has(t.title) ? " checked" : ""}>
      ${esc(t.label || t.title)} <span class="muted small">${t_("n_new", {n: t.unseen})}</span></label>`).join("")).join("");
  $("topic-picker").innerHTML = html || `<p class="muted">${t_("reserve_empty_picker")}</p>`;
}

$("topic-picker").addEventListener("change", e => {
  if (e.target.type !== "checkbox") return;
  e.target.checked ? P.picked.add(e.target.value) : P.picked.delete(e.target.value);
  store("picked", JSON.stringify([...P.picked]));
  updateStartButton();
});
$("quick-picks").addEventListener("click", e => {
  const pick = e.target.closest("[data-pick]")?.dataset.pick;
  if (!pick) return;
  P.picked = new Set(pick === "none" ? [] : P.topics.filter(t => t.total &&
    (t.kind === pick || t.level === pick)).map(t => t.title));
  if (pick === "particle") { $("hard-mode").checked = true; store("hardMode", "1"); }  // « all particles » = no list
  store("picked", JSON.stringify([...P.picked]));
  renderPicker();
  updateStartButton();
});

async function loadHome() {
  try {
    const [stats, topics] = await Promise.all([api("/api/stats"), api("/api/topics")]);
    renderSummary(stats);
    P.topics = topics.topics;
    const current = P.topics.filter(t => t.state === "current");
    const reserve = P.topics.reduce((n, t) => n + t.total, 0);
    const names = current.map(t => `<strong>${esc(t.label || t.title)}</strong>`).join(t_("and"));
    $("start-text").innerHTML = !reserve
      ? t_("reserve_empty")
      : (stats.due_now ? tn("due_then_new", stats.due_now) : t_("nothing_due"))
        + (current.length ? t_("on_topics", {names}) : ".");
    const empty = current.filter(t => !t.unseen);
    $("daily-empty").hidden = !empty.length || !reserve;
    $("daily-empty").innerHTML = empty.length ? `${t_("no_more_new", {topics: empty.map(t => esc(t.label || t.title)).join(", ")})}
      <button class="ghost" id="btn-goto-fill">${t_("goto_fill")}</button>` : "";
    const goto = $("btn-goto-fill");
    if (goto) goto.onclick = () => showTab("progress");
    renderPicker();
    setMode(P.mode);
  } catch (e) { toast(t("stats_error", {e: e.message})); }
}

async function startSession(newCount) {
  const n = newCount ?? $("new-select").value;
  const url = P.mode === "practice"
    ? `/api/session?mode=practice&new=${n}&topics=${encodeURIComponent([...P.picked].join("|"))}`
    : `/api/session?new=${n}`;
  try {
    const data = await api(url);
    renderSummary(data.stats);
    if (!data.items.length) {
      toast(P.mode === "practice" ? t("nothing_practice") : data.stats.unseen ? t("nothing_due_pick") : t("all_done"));
      return;
    }
    Object.assign(S, {queue: data.items, pos: 0, done: 0, firstTry: 0});
    $("session-start").hidden = true;
    $("session-end").hidden = true;
    $("session-run").hidden = false;
    showExercise();
  } catch (e) { toast(t("start_error", {e: e.message})); }
}

function showExercise() {
  const ex = S.queue[S.pos];
  S.current = ex;
  S.solved = false;
  ex._attempts = ex._attempts || 0;
  const box = $("exo");
  box.classList.remove("ok", "ko");

  const badge = $("exo-status");
  badge.textContent = ex._retry ? t("badge_retry") : ex.status === "review" ? t("badge_review") : t("badge_new");
  badge.classList.toggle("review", ex.status === "review" || ex._retry);
  $("exo-topic").textContent = ex.topic_label || ex.topic;
  $("exo-count").textContent = `${S.pos + 1} / ${S.queue.length}`;
  $("progress-fill").style.width = `${100 * S.pos / S.queue.length}%`;

  const allowed = ex.allowed_answers || [];
  if (ex.cue) {
    $("exo-choices").innerHTML = `${t("verb_to_conjugate")}<span class="ans" lang="ja">${esc(ex.cue)}</span>` +
      (ex.cue_reading ? ` <span class="muted" lang="ja">（${esc(ex.cue_reading)}）</span>` : "") +
      ` <span class="muted small">· ${t("kana_ok")}</span>`;
  } else {
    $("exo-choices").innerHTML = allowed.length && !$("hard-mode").checked
      ? t("possible_answers") + allowed.map(a => `<span class="ans" lang="ja">${esc(a)}</span>`).join("") : "";
  }

  $("exo-mcq").hidden = !ex.choices;
  if (ex.choices) {  // multiple choice (JLPT questions)
    $("exo-choices").innerHTML = "";
    $("exo-sentence").innerHTML = questionHtml(ex.question);
    $("exo-mcq").innerHTML = choicesHtml(ex.choices);
  } else {
    const [before, after] = ex.sentence.split(BLANK);
    const width = Math.max(4, (ex.answers[0] || "").length + 2);
    $("exo-sentence").innerHTML = `${esc(before)}<input id="answer" lang="ja" autocomplete="off" spellcheck="false"
      aria-label="${t("answer_label")}" style="width:${width}em">${esc(after ?? "")}`;
  }
  $("exo-reading").textContent = ex.reading || "";
  $("exo-translation").textContent = ex.show_translation ? (ex.translation || "") : "";
  $("exo-new").innerHTML = (ex.new_words || []).length ? `${t("new_words")}<span lang="ja">${ex.new_words.map(esc).join("、")}</span>` : "";

  $("exo-hint").hidden = true;
  $("exo-hint").textContent = "💡 " + (ex.hint || "");
  $("btn-hint").hidden = !ex.hint;
  $("btn-show").hidden = true;
  $("btn-check").hidden = !!ex.choices;
  $("exo-feedback").hidden = true;
  $("after-actions").hidden = true;
  $("btn-unsure").hidden = true;
  updateUndo();
  if (ex.choices) $("exo-mcq").querySelector("button").focus(); else $("answer").focus();
}

// A JLPT question: 【word】 is underlined, the rest is plain text.
function questionHtml(q) {
  return esc(q).replace(/【(.*?)】/g, "<u>$1</u>");
}
function choicesHtml(choices) {
  return choices.map((c, i) => `<button data-choice="${i}" lang="ja"><span class="n">${i + 1}</span>${esc(c)}</button>`).join("");
}

async function choose(i) {
  const ex = S.current;
  if (S.solved) return;
  const ok = i === ex.answer_index;
  const buttons = $("exo-mcq").querySelectorAll("button");
  buttons[ex.answer_index].classList.add("right");
  if (!ok) buttons[i].classList.add("wrong");
  ex._given = ex.choices[i];
  ex._attempts += 1;
  $("exo").classList.toggle("ok", ok);
  $("exo").classList.toggle("ko", !ok);
  await record(ok, ex.choices[i]);
  if (!ok) requeue(ex);
  const full = ex.full_sentence ? `<br><span lang="ja">${esc(ex.full_sentence)}</span>` : "";
  S.solved = true;
  $("exo-feedback").hidden = false;
  $("exo-feedback").innerHTML = solutionHtml(ex, (ok ? t("correct") : t("wrong_answer", {a: esc(ex.answers[0])})) + full);
  $("btn-check").hidden = true;
  $("after-actions").hidden = false;
  $("btn-unsure").hidden = !(ok && ex._firstOk && !ex._retry);
  updateUndo();
  $("btn-next").focus();
}
$("exo-mcq").addEventListener("click", e => {
  const b = e.target.closest("button[data-choice]");
  if (b) choose(+b.dataset.choice);
});

function field() { return $("answer") || {value: "", readOnly: false, focus() {}, select() {}}; }

async function record(correct, answer) {
  const ex = S.current;
  if (ex._recorded) return null;  // only the first attempt counts
  ex._recorded = true;
  ex._firstOk = !!correct;
  S.done += 1;
  if (correct) S.firstTry += 1;
  try {
    const data = await api("/api/answer", {id: ex.id, correct, answer});
    renderSummary(data.stats);
    ex._schedule = data.schedule;
    return data.schedule;
  } catch (e) {
    toast(t("not_saved", {e: e.message}));
    return null;
  }
}

function nextReviewText(schedule) {
  if (!schedule) return "";
  const d = schedule.interval;
  return `<div class="next-review">${t("next_review", {when: d <= 1 ? t("tomorrow") : t("in_days", {n: d})})}</div>`;
}

function solutionHtml(ex, message) {
  const schedule = ex._retry ? null : ex._schedule;
  const others = ex.answers.length > 1 ? `<br>${t("accepted")}<span lang="ja">${ex.answers.map(esc).join(" / ")}</span>` : "";
  const tr = ex.translation && !ex.show_translation ? `<br><span class="tr">${esc(ex.translation)}</span>` : "";
  const expl = ex.explanation ? `<br>${esc(ex.explanation)}` : "";
  const src = ex.source_url ? `<br><a href="${esc(ex.source_url)}" target="_blank" rel="noopener">${esc(ex.source || "source")}</a>` : "";
  return `${message}${others}${tr}${expl}${src}${nextReviewText(schedule)}`;
}

async function check() {
  if (S.solved) return next();
  const ex = S.current, value = field().value;
  if (!norm(value)) { field().focus(); return; }
  ex._attempts += 1;
  ex._given = ex._given || value;
  const ok = ex.answers.some(a => norm(a) === norm(value));
  $("exo").classList.toggle("ok", ok);
  $("exo").classList.toggle("ko", !ok);
  const fb = $("exo-feedback");
  fb.hidden = false;
  await record(ok, value);
  if (ok) {
    solve(solutionHtml(ex, t("correct")));
  } else {
    fb.innerHTML = t("try_again");
    $("btn-show").hidden = false;
    requeue(ex);
    updateUndo();
    field().select();
  }
}

function requeue(ex) {
  // A missed exercise comes back once at the end of the session (not recorded again).
  if (ex._requeued || ex._retry) return;
  ex._requeued = true;
  S.queue.push(Object.assign({}, ex, {_retry: true, _recorded: true, _attempts: 0, _requeued: true, _given: "", _schedule: null}));
}

async function showAnswer() {
  const ex = S.current;
  await record(false, "");
  requeue(ex);
  field().value = ex.answers[0];
  $("exo").classList.remove("ok");
  $("exo").classList.add("ko");
  solve(solutionHtml(ex, t("the_answer", {a: esc(ex.answers[0])})));
}

function solve(html) {
  S.solved = true;
  field().readOnly = true;
  $("exo-feedback").hidden = false;
  $("exo-feedback").innerHTML = html;
  $("btn-show").hidden = true;
  $("btn-check").hidden = true;
  $("after-actions").hidden = false;
  const ex = S.current;
  $("btn-unsure").hidden = !(ex._firstOk && !ex._retry && $("exo").classList.contains("ok"));
  updateUndo();
  $("btn-next").focus();
}

// ---------------- undo, « je ne maîtrise pas », suspend, report ----------------

function updateUndo() {
  const ex = S.current;
  const answered = ex && (S.solved || ex._attempts > 0);
  const b = $("btn-undo");
  b.hidden = !(answered || S.pos > 0);
  b.textContent = answered ? t("undo_answer") : t("undo_previous");
}

// Misclick or typo: the answer is forgotten (and its review schedule restored), the exercise starts again.
async function undo() {
  if ($("session-run").hidden) return;
  let ex = S.current;
  if (!(S.solved || ex._attempts > 0)) {
    if (S.pos === 0) return;
    S.pos -= 1;
    ex = S.queue[S.pos];
  }
  if (ex._recorded && !ex._retry) {
    try {
      const d = await api("/api/answer/undo", {id: ex.id});
      renderSummary(d.stats);
    } catch (e) { toast(t("undo_error", {e: e.message})); return; }
    S.done -= 1;
    if (ex._firstOk) S.firstTry -= 1;
  }
  if (ex._requeued && !ex._retry) {  // the copy added at the end of the session
    const k = S.queue.findIndex((q, j) => j > S.pos && q._retry && q.id === ex.id);
    if (k >= 0) S.queue.splice(k, 1);
  }
  Object.assign(ex, {_recorded: !!ex._retry, _requeued: !!ex._retry, _attempts: 0, _given: "",
                     _schedule: null, _firstOk: undefined});
  showExercise();
}

// Right, but by luck: the answer counts as wrong (comes back at the end and tomorrow).
async function unsure() {
  const ex = S.current;
  try {
    const d = await api("/api/answer", {id: ex.id, correct: false, answer: ex._given || "", replace: true});
    renderSummary(d.stats);
    ex._schedule = d.schedule;
  } catch (e) { toast(e.message); return; }
  if (ex._firstOk) S.firstTry -= 1;
  ex._firstOk = false;
  requeue(ex);
  $("exo").classList.remove("ok");
  $("exo").classList.add("ko");
  $("exo-feedback").innerHTML = solutionHtml(ex, t("marked_unsure"));
  $("btn-unsure").hidden = true;
  $("btn-next").focus();
}

async function dropCurrent(action) {
  const ex = S.current;
  try {
    await api("/api/reviews/action", {ids: [ex.id], action});
  } catch (e) { toast(e.message); return; }
  S.queue = S.queue.filter((q, j) => j <= S.pos || q.id !== ex.id);
  toast(action === "report" ? t("reported") : t("suspended"));
  next();
}

function next() {
  S.pos += 1;
  if (S.pos < S.queue.length) return showExercise();
  $("progress-fill").style.width = "100%";
  $("session-run").hidden = true;
  $("session-end").hidden = false;
  const st = S.lastStats;
  $("end-text").innerHTML = tn("end_text", S.done, {k: S.firstTry}) +
    (st ? `<br><span class="muted">${t("end_tomorrow", {due: st.due_tomorrow, unseen: st.unseen})}</span>` : "");
  $("btn-more").hidden = !(st && st.unseen);
}

$("btn-start").addEventListener("click", () => startSession());
$("btn-more").addEventListener("click", () => startSession(5));
$("btn-home").addEventListener("click", () => { $("session-end").hidden = true; $("session-start").hidden = false; loadHome(); });
$("btn-check").addEventListener("click", check);
$("btn-show").addEventListener("click", showAnswer);
$("btn-next").addEventListener("click", next);
$("btn-hint").addEventListener("click", () => { $("exo-hint").hidden = false; });
$("btn-undo").addEventListener("click", undo);
$("btn-unsure").addEventListener("click", unsure);
$("btn-suspend").addEventListener("click", () => dropCurrent("suspend"));
$("btn-report").addEventListener("click", () => dropCurrent("report"));
$("btn-readings").addEventListener("click", e => {
  const hidden = document.body.classList.toggle("hide-readings");
  e.target.textContent = hidden ? t("show_reading") : t("hide_reading");
  store("hideReadings", hidden ? "1" : "0");
});
$("hard-mode").checked = store("hardMode") === "1";
$("hard-mode").addEventListener("change", e => store("hardMode", e.target.checked ? "1" : "0"));
if (store("hideReadings") === "1") {
  document.body.classList.add("hide-readings");
  $("btn-readings").textContent = t("show_reading");
}
$("btn-ask").addEventListener("click", () => {
  const ex = S.current;
  if (C.mode !== "prof") setChatMode("prof");
  setChatContext({
    sentence: ex.sentence || ex.question, full_sentence: ex.full_sentence, answers: ex.answers, cue: ex.cue,
    topic: ex.topic_label || ex.topic, choices: ex.choices,
    translation: ex.translation, explanation: ex.explanation, given: ex._given || "",
  });
  showTab("chat");
});

document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && $("tab-session").classList.contains("active")
      && !$("session-run").hidden && !(e.target.tagName === "INPUT" && !e.target.readOnly && e.target.value)
      && e.target.tagName !== "TEXTAREA") {
    e.preventDefault();
    undo();
    return;
  }
  if (/^[1-4]$/.test(e.key) && e.target.tagName !== "TEXTAREA" && e.target.tagName !== "INPUT") {
    if ($("tab-session").classList.contains("active") && !$("session-run").hidden && S.current?.choices && !S.solved) {
      choose(+e.key - 1);
      return;
    }
    if ($("tab-jlpt").classList.contains("active") && !$("exam-run").hidden) {
      examPick(+e.key - 1);
      return;
    }
  }
  if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;  // Enter confirms Japanese IME input
  if (!$("tab-session").classList.contains("active") || $("session-run").hidden) return;
  if (e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
  if (e.target.tagName === "BUTTON" && e.target.id !== "btn-next") return;
  if (S.current?.choices && !S.solved) return;  // multiple choice: click or 1-4
  e.preventDefault();
  if (S.solved) next(); else check();
});

// ======================================================================
// Chat with the tutor
// ======================================================================

const C = {mode: store("chatMode") || "prof", id: "", loaded: false, busy: false, context: null,
           scenario: store("chatScenario") || "free"};
C.id = store("conversation-" + C.mode) || (C.mode === "prof" ? (store("conversation") || "main") : C.mode + "-1");
const CHAT_INTRO = {prof: t("intro_prof"), conversation: t("intro_conversation"), quiz: t("intro_quiz")};

function markdown(text) {
  // Tiny, safe renderer: escape first, then **bold**, `code`, lists and paragraphs.
  const lines = esc(text).split("\n");
  let html = "", list = null, para = [];
  const inline = s => s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
  const flushPara = () => { if (para.length) { html += `<p>${para.map(inline).join("<br>")}</p>`; para = []; } };
  const flushList = () => {
    if (!list) return;
    const start = list.tag === "ol" && list.start > 1 ? ` start="${list.start}"` : "";
    html += `<${list.tag}${start}>${list.items.map(i => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`;
    list = null;
  };
  for (const line of lines) {
    const bullet = line.match(/^\s*[-*・]\s+(.*)/), num = line.match(/^\s*(\d+)[.)]\s+(.*)/);
    if (bullet || num) {
      flushPara();
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tag !== tag) { flushList(); list = {tag, items: [], start: num ? +num[1] : 1}; }
      list.items.push(bullet ? bullet[1] : num[2]);
    } else if (!line.trim()) {
      flushPara(); flushList();
    } else {
      flushList(); para.push(line.replace(/^#+\s*/, ""));
    }
  }
  flushPara(); flushList();
  return html;
}

function addMessage(role, text) {
  const empty = $("messages").querySelector(".empty-chat");
  if (empty) empty.remove();
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.setAttribute("lang", LANG);
  div.innerHTML = role === "user" ? esc(text).replace(/\n/g, "<br>") : markdown(text);
  $("messages").appendChild(div);
  $("messages").scrollTop = $("messages").scrollHeight;
  return div;
}

function emptyChat() {
  const start = C.mode === "prof" ? "" : `<br><button class="primary chat-start" id="btn-chat-start">${t("start")}</button>`;
  $("messages").innerHTML = `<div class="empty-chat">${CHAT_INTRO[C.mode]}${start}</div>`;
  const b = $("btn-chat-start");
  if (b) b.onclick = () => send(C.mode === "quiz" ? t("quiz_me") : "よろしくお願いします。");
}

function setChatMode(mode) {
  C.mode = mode;
  store("chatMode", mode);
  C.id = store("conversation-" + mode) || (mode === "prof" ? (store("conversation") || "main") : mode + "-1");
  document.querySelectorAll("[data-chat-mode]").forEach(b => b.classList.toggle("active", b.dataset.chatMode === mode));
  $("chat-scenario").hidden = mode !== "conversation";
  $("chips").hidden = mode !== "prof";
  $("messages").innerHTML = "";
  C.loaded = false;
  loadChat(true);
}
document.querySelectorAll("[data-chat-mode]").forEach(b => b.addEventListener("click", () => setChatMode(b.dataset.chatMode)));
$("chat-scenario").value = C.scenario;
$("chat-scenario").addEventListener("change", e => {
  C.scenario = e.target.value;
  store("chatScenario", C.scenario);
  $("btn-new-chat").click();  // a new situation = a new conversation
});

async function loadChat(force) {
  if (C.loaded && !force) return;
  C.loaded = true;
  const box = $("messages");
  if (!box.children.length) emptyChat();
  try {
    const data = await api(`/api/chat/history?conversation=${encodeURIComponent(C.id)}`);
    if (!data.messages.length) return;
    // Put the history BEFORE anything already shown (a message may have been sent meanwhile).
    const current = [...box.children].filter(el => !el.classList.contains("empty-chat"));
    box.innerHTML = "";
    data.messages.forEach(m => addMessage(m.role, m.content));
    current.forEach(el => box.appendChild(el));
    box.scrollTop = box.scrollHeight;
  } catch (e) { /* the history is optional */ }
}

function setChatContext(ex) {
  C.context = ex;
  $("chat-context").hidden = !ex;
  $("chat-context-text").innerHTML = ex ? `${t("question_about")}<span lang="ja">${esc(ex.full_sentence || ex.sentence)}</span>` : "";
  if (ex) $("chat-input").value = ex.given && !ex.answers.some(a => norm(a) === norm(ex.given))
    ? t("why_not", {a: ex.answers[0], b: ex.given}) : t("why_answer");
}

async function send(text) {
  if (C.busy || !text.trim()) return;
  C.busy = true;
  $("btn-send").disabled = true;
  addMessage("user", text);
  const bubble = addMessage("assistant", "");
  bubble.classList.add("typing");
  let answer = "";
  const context = C.context;
  setChatContext(null);
  try {
    const res = await fetch("/api/chat", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({conversation: C.id, message: text, exercise: context, mode: context ? "prof" : C.mode,
                            scenario: C.scenario}),
    });
    if (!res.ok || !res.body) throw new Error((await res.json().catch(() => ({}))).error || `HTTP ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      let nl;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        const msg = JSON.parse(line);
        if (msg.error) throw new Error(msg.error);
        if (msg.refs) {
          const refs = document.createElement("div");
          refs.className = "refs";
          refs.textContent = t("references") + msg.refs.join(" · ");
          bubble.after(refs);
        }
        if (msg.delta) {
          answer += msg.delta;
          bubble.innerHTML = markdown(answer);
          $("messages").scrollTop = $("messages").scrollHeight;
        }
      }
    }
    if (!answer) throw new Error(t("empty_answer"));
  } catch (e) {
    if (!answer) bubble.remove();
    addMessage("error", e.message);
  } finally {
    bubble.classList.remove("typing");
    C.busy = false;
    $("btn-send").disabled = false;
    $("chat-input").focus();
  }
}

$("composer").addEventListener("submit", e => {
  e.preventDefault();
  const text = $("chat-input").value;
  $("chat-input").value = "";
  send(text);
});
$("chat-input").addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
    e.preventDefault();
    $("composer").requestSubmit();
  }
});
setChatMode(C.mode);
$("chips").addEventListener("click", e => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  $("chat-input").value = chip.dataset.text;
  $("chat-input").focus();
  if (!chip.dataset.text.endsWith(" ")) $("composer").requestSubmit();
});
$("btn-new-chat").addEventListener("click", () => {
  C.id = C.mode + "-" + Date.now();
  store("conversation-" + C.mode, C.id);
  setChatContext(null);
  emptyChat();
});
$("btn-drop-context").addEventListener("click", () => setChatContext(null));

// ======================================================================
// Progress
// ======================================================================

async function loadProgress() {
  try {
    const s = await api("/api/stats");
    renderSummary(s);
    const pct = s.all_time.done ? Math.round(100 * s.all_time.correct / s.all_time.done) : 0;
    const card = (value, label) => `<div class="stat"><div class="value">${value}</div><div class="label">${label}</div></div>`;
    $("stat-cards").innerHTML = [
      card(s.today.done, t("done_today")),
      card(s.due_tomorrow, t("due_tomorrow")),
      card(s.day_streak, t("days_streak")),
      card(s.learning, t("learning")),
      card(s.mastered, t("mastered")),
      card(`${pct} %`, t("first_try", {n: s.all_time.done})),
    ].join("");
    await loadProgramme();
    loadReviews();
    loadBank();
    loadTeacher();
    $("weak-card").hidden = !s.weakest.length;
    $("weak-list").innerHTML = s.weakest.map(w =>
      `<li>${t("weak_line", {topic: esc(label(w.topic)), pct: Math.round(100 * w.correct / w.done), n: w.done})}</li>`).join("");
  } catch (e) { toast(t("stats_error", {e: e.message})); }
}

async function loadProgramme() {
  const data = await api("/api/topics");
  P.topics = data.topics;
  $("topics-table").innerHTML = `<tr><th></th><th>${t_("h_topic")}</th><th>${t_("h_state")}</th><th class="num">${t_("h_rate")}</th>
      <th class="num">${t_("h_new_total")}</th><th></th></tr>` +
    P.topics.map(t => {
      const rate = t.answers ? `${Math.round(100 * t.rate)} % <span class="muted small">(${t.answers})</span>` : "—";
      const action = t.state === "custom" ? "" : t.flagged
        ? `<button data-known="0" data-title="${esc(t.title)}">${t_("known_undo")}</button>`
        : t.state !== "passed" ? `<button data-known="1" data-title="${esc(t.title)}" title="${t_("known_title")}">${t_("known_set")}</button>` : "";
      return `<tr><td class="level">${esc(t.level)}</td><td>${esc(t.label || t.title)}</td>
        <td><span class="state ${t.state}" title="${esc(t.why)}">${STATE_LABEL[t.state]}</span></td>
        <td class="num">${rate}</td><td class="num">${t.unseen} / ${t.total}</td><td>${action}</td></tr>`;
    }).join("");
}

$("topics-table").addEventListener("click", async e => {
  const b = e.target.closest("button[data-known]");
  if (!b) return;
  try {
    await api("/api/topic_known", {title: b.dataset.title, known: b.dataset.known === "1"});
    await loadProgramme();
    loadHome();
  } catch (err) { toast(err.message); }
});

// ---------------- reviews managed by hand ----------------

const R = {items: []};

function dueText(r) {
  if (!r.seen) return `<span class="muted">${t("never_seen")}</span>`;
  if (r.suspended) return `<span class="muted">${t("is_suspended")}</span>`;
  const today = new Date().toISOString().slice(0, 10);
  return r.due <= today ? `<span class="due-now">${t("today")}</span>` : esc(r.due);
}

async function loadReviews() {
  const sel = $("rev-topic"), current = sel.value;
  sel.innerHTML = `<option value="">${t("all")}</option>` +
    (P.topics || []).filter(x => x.total).map(x => `<option value="${esc(x.title)}"${x.title === current ? " selected" : ""}>${esc(x.label || x.title)}</option>`).join("");
  const q = new URLSearchParams({topic: sel.value, q: $("rev-q").value.trim(), unseen: $("rev-unseen").checked ? "1" : "0"});
  try {
    R.items = (await api("/api/reviews?" + q)).items;
  } catch (e) { toast(e.message); return; }
  $("rev-count").textContent = tn("rev_count", R.items.length);
  $("rev-table").innerHTML = `<tr><th><input type="checkbox" id="rev-all" aria-label="${t("check_all")}"></th><th>${t("h_exercise")}</th>
      <th>${t("h_answer")}</th><th>${t("h_next")}</th><th class="num">${t("h_interval")}</th><th class="num">${t("h_lapses")}</th></tr>` +
    R.items.map(r => `<tr class="${r.suspended ? "suspended" : ""}">
      <td><input type="checkbox" data-id="${r.id}"></td>
      <td class="jp" lang="ja">${esc(r.text).replace(/【(.*?)】/g, "<u>$1</u>")}<div class="muted small">${esc(r.topic_label || r.topic)}</div></td>
      <td lang="ja">${esc(r.answer)}</td><td>${dueText(r)}</td>
      <td class="num">${r.seen ? t("days_short", {n: r.interval}) : ""}</td><td class="num">${r.seen ? r.lapses : ""}</td></tr>`).join("");
}

async function reviewAction(action) {
  const ids = [...document.querySelectorAll("#rev-table input[data-id]:checked")].map(c => +c.dataset.id);
  if (!ids.length) { toast(t("tick_first")); return; }
  try {
    const d = await api("/api/reviews/action", {ids, action});
    renderSummary(d.stats);
    toast(t("act_" + action, {n: d.done}));
    loadReviews();
    loadProgramme();
  } catch (e) { toast(e.message); }
}

$("rev-topic").addEventListener("change", loadReviews);
$("rev-unseen").addEventListener("change", loadReviews);
$("rev-q").addEventListener("input", () => { clearTimeout(R.timer); R.timer = setTimeout(loadReviews, 300); });
$("rev-table").addEventListener("change", e => {
  if (e.target.id === "rev-all") document.querySelectorAll("#rev-table input[data-id]").forEach(c => { c.checked = e.target.checked; });
});
$("rev-today").addEventListener("click", () => reviewAction("due_today"));
$("rev-suspend").addEventListener("click", () => reviewAction("suspend"));
$("rev-unsuspend").addEventListener("click", () => reviewAction("unsuspend"));
$("rev-report").addEventListener("click", () => reviewAction("report"));

// ---------------- the teacher's model ----------------

const TM = {settings: null};

function teacherForm() {
  const st = TM.settings;
  const provider = $("teacher-provider").value;
  const cloud = provider !== "local";
  $("teacher-model-box").hidden = !cloud;
  $("teacher-key-box").hidden = !cloud;
  const current = st.chat_model || "";
  if (cloud) {
    $("teacher-model").value = current.startsWith(provider + ":") ? current.split(":").slice(1).join(":") : st.defaults[provider];
    $("teacher-key").value = "";
    $("teacher-key").placeholder = st.api_keys_set[provider] ? "••••••••" : "";
    $("teacher-help").textContent = t("teacher_help_" + provider) + (st.api_keys_set[provider] ? " " + t("teacher_key_set") : "");
  } else {
    $("teacher-help").textContent = t("teacher_help_local", {model: st.local});
  }
}

async function loadTeacher() {
  try {
    TM.settings = await api("/api/settings");
    const current = TM.settings.chat_model || "";
    $("teacher-provider").value = /^(anthropic|openai):/.test(current) ? current.split(":")[0] : "local";
    teacherForm();
  } catch (e) { /* optional */ }
}
$("teacher-provider").addEventListener("change", teacherForm);
$("btn-teacher-save").addEventListener("click", async () => {
  const provider = $("teacher-provider").value;
  const changes = {chat_model: provider === "local" ? "" : `${provider}:${$("teacher-model").value.trim()}`};
  if (provider !== "local" && $("teacher-key").value.trim()) changes.api_keys = {[provider]: $("teacher-key").value.trim()};
  try {
    await api("/api/settings", changes);
    toast(t("saved"));
    await loadTeacher();
    loadStatus();
  } catch (e) { toast(e.message); }
});

// ---------------- shared bank ----------------

async function loadBank() {
  try {
    const [b, st] = await Promise.all([api("/api/bank"), api("/api/settings")]);
    $("bank-status").textContent = (b.last_pull
      ? t("bank_last", {date: b.last_pull.replace("T", " ").slice(0, 16), version: b.version ?? "?", count: b.count ?? "?",
                        added: b.last_added})
      : t("bank_never")) + (b.sent ? t("bank_sent", {n: b.sent}) : "");
    $("btn-bank-send").hidden = !b.can_contribute;
    $("bank-url").value = st.bank_url || "";
    $("bank-url").placeholder = b.url;
    $("bank-dest").value = st.bank_contribute || "";
    $("bank-name").value = st.contributor || "";
    $("bank-token").placeholder = st.bank_token_set ? "••••••••" : "";
  } catch (e) { /* optional */ }
}

async function bankJob(path) {
  try {
    renderFill(await api(path, {}));
    pollFill.was = true;
    setTimeout(pollFill, 1000);
  } catch (e) { toast(e.message); }
}
$("btn-bank-sync").addEventListener("click", () => bankJob("/api/bank/sync"));
$("btn-bank-send").addEventListener("click", () => bankJob("/api/bank/contribute"));
$("btn-bank-save").addEventListener("click", async () => {
  const changes = {bank_url: $("bank-url").value.trim(), bank_contribute: $("bank-dest").value.trim(),
                   contributor: $("bank-name").value.trim()};
  if ($("bank-token").value) changes.bank_token = $("bank-token").value.trim();
  try {
    await api("/api/settings", changes);
    $("bank-token").value = "";
    toast(t("saved"));
    loadBank();
  } catch (e) { toast(e.message); }
});

// ---------------- filling the reserve ----------------

function renderFill(f) {
  document.querySelectorAll(".job-log").forEach(log => {
    log.hidden = !f.log.length;
    log.textContent = (f.title ? `— ${f.title} (${f.started || ""}${f.finished ? " → " + f.finished : ""}) —\n` : "") + f.log.join("\n");
    log.scrollTop = log.scrollHeight;
  });
  $("btn-fill").disabled = f.running;
  $("btn-fill").textContent = f.running ? t("running", {title: f.title || t("filling")}) : t("fill");
  $("btn-fill-stop").hidden = !f.running;
  $("btn-jlpt-fill").disabled = f.running;
  $("jlpt-fill-state").textContent = f.running ? t("running_work", {title: f.title}) : "";
}

async function pollFill() {
  try {
    const f = await api("/api/fill");
    renderFill(f);
    if (f.running) { setTimeout(pollFill, 1500); return; }
    if (pollFill.was) {
      toast(t("added", {title: f.title || t("reserve_word"), n: f.added ?? 0}));
      loadHome(); loadProgramme(); loadBank();
      if ($("tab-jlpt").classList.contains("active")) loadJlpt();
    }
    pollFill.was = false;
  } catch (e) { /* server restarting */ }
}

$("btn-fill").addEventListener("click", async () => {
  try {
    const f = await api("/api/fill", {target: +$("fill-target").value, all: $("fill-all").checked});
    renderFill(f);
    pollFill.was = true;
    setTimeout(pollFill, 1000);
  } catch (e) { toast(e.message); }
});
$("btn-fill-stop").addEventListener("click", () => api("/api/fill/stop", {}).catch(() => {}));

// ---------------- automatic tasks at startup ----------------

async function loadSettings() {
  try {
    const st = await api("/api/settings");
    document.querySelectorAll("[data-setting]").forEach(cb => { cb.checked = !!st[cb.dataset.setting]; });
    return st;
  } catch (e) { return {}; }
}
document.querySelectorAll("[data-setting]").forEach(cb => cb.addEventListener("change", () =>
  api("/api/settings", {[cb.dataset.setting]: cb.checked}).catch(err => toast(err.message))));

// ======================================================================
// JLPT
// ======================================================================

const J = {level: store("jlptLevel") || "", overview: null, types: new Set(JSON.parse(store("jlptTypes") || "[]"))};
const TYPE_SHORT = {kanji_reading: "漢字読み", orthography: "表記", vocab: "文脈規定", grammar: "文法形式", ordering: "並べ替え ★"};

async function loadJlpt() {
  try {
    if (!J.level) J.level = (await loadSettings()).jlpt_level || "N4";
    const o = await api(`/api/jlpt/overview?level=${J.level}`);
    J.overview = o;
    $("jlpt-level").innerHTML = o.levels.map(l => `<option${l === o.level ? " selected" : ""}>${l}</option>`).join("");
    $("jlpt-types").innerHTML = o.types.map(t => `<div class="stat"><div class="value">${t.unseen} <span class="muted small">/ ${t.total}</span></div>
      <div class="label" lang="ja">${esc(t.label)}</div></div>`).join("");
    const notes = [];
    if (!o.lexicon) notes.push(t("jlpt_levels_approx"));
    if (!o.kanji) notes.push(t("jlpt_no_kanji"));
    $("jlpt-note").textContent = t("jlpt_counts") + notes.join(" ");
    if (!J.types.size) o.types.forEach(t => J.types.add(t.type));
    $("jlpt-type-picker").innerHTML = o.types.map(t => `<label><input type="checkbox" value="${t.type}"${J.types.has(t.type) ? " checked" : ""}>
      <span lang="ja">${esc(t.label)}</span> <span class="muted small">(${t.total})</span></label>`).join("");
    const plan = o.types.filter(t => t.exam).map(t => `${TYPE_SHORT[t.type]} ${t.exam}`).join(" · ");
    const total = o.types.reduce((n, t) => n + t.exam, 0);
    $("jlpt-exam-plan").textContent = t("exam_plan", {n: total, plan});
    $("btn-jlpt-exam").disabled = !o.types.some(t => t.total);
    $("btn-jlpt-practice").disabled = !o.types.some(t => t.total);
    $("jlpt-history").innerHTML = o.exams.length ? `<table class="topics"><tr><th>${t("h_date")}</th><th>${t("h_level")}</th><th class="num">${t("h_score")}</th><th class="num">${t("h_duration")}</th></tr>` +
      o.exams.map(x => `<tr><td>${esc(x.taken_at.replace("T", " ").slice(0, 16))}</td><td>${esc(x.level)}</td>
        <td class="num">${x.score} / ${x.total} (${Math.round(100 * x.score / Math.max(1, x.total))} %)</td>
        <td class="num">${Math.round(x.seconds / 60)} min</td></tr>`).join("") + "</table>" : "";
    renderFill(await api("/api/fill"));
  } catch (e) { toast("JLPT : " + e.message); }
}

$("jlpt-level").addEventListener("change", e => {
  J.level = e.target.value;
  store("jlptLevel", J.level);
  api("/api/settings", {jlpt_level: J.level}).catch(() => {});
  loadJlpt();
});
$("jlpt-type-picker").addEventListener("change", e => {
  e.target.checked ? J.types.add(e.target.value) : J.types.delete(e.target.value);
  store("jlptTypes", JSON.stringify([...J.types]));
});
$("btn-jlpt-fill").addEventListener("click", async () => {
  try {
    renderFill(await api("/api/jlpt/fill", {level: J.level, per_type: 10}));
    pollFill.was = true;
    setTimeout(pollFill, 1000);
  } catch (e) { toast(e.message); }
});

$("btn-jlpt-practice").addEventListener("click", async () => {
  try {
    const data = await api(`/api/jlpt/practice?level=${J.level}&count=${$("jlpt-count").value}&types=${[...J.types].join("|")}`);
    if (!data.items.length) return toast(t("no_questions"));
    Object.assign(S, {queue: data.items, pos: 0, done: 0, firstTry: 0});
    showTab("session");
    $("session-start").hidden = true;
    $("session-end").hidden = true;
    $("session-run").hidden = false;
    showExercise();
  } catch (e) { toast(e.message); }
});

// ---------------- mock exam ----------------

const E = {items: [], pos: 0, picks: [], started: 0, seconds: 0, timer: null};

$("btn-jlpt-exam").addEventListener("click", async () => {
  try {
    const data = await api(`/api/jlpt/exam?level=${J.level}`);
    if (!data.items.length) return toast(t("not_enough"));
    Object.assign(E, {items: data.items, pos: 0, picks: data.items.map(() => null), started: Date.now(), seconds: data.minutes * 60});
    $("jlpt-home").hidden = true;
    $("exam-result").hidden = true;
    $("exam-run").hidden = false;
    clearInterval(E.timer);
    E.timer = setInterval(tick, 1000);
    tick();
    showExamQuestion();
  } catch (e) { toast(e.message); }
});

function tick() {
  const left = Math.max(0, E.seconds - Math.round((Date.now() - E.started) / 1000));
  $("exam-timer").textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
  $("exam-timer").classList.toggle("low", left < 120);
  if (!left) finishExam();
}

function showExamQuestion() {
  const q = E.items[E.pos];
  $("exam-section").innerHTML = `<span lang="ja">${esc(TYPE_SHORT[q.qtype] || q.topic)}</span>`;
  $("exam-count").textContent = t("exam_count", {i: E.pos + 1, n: E.items.length, k: E.picks.filter(p => p !== null).length});
  $("exam-fill").style.width = `${100 * E.pos / E.items.length}%`;
  $("exam-question").innerHTML = questionHtml(q.question) + (q.show_translation && q.translation ? `<div class="tr">${esc(q.translation)}</div>` : "");
  $("exam-choices").innerHTML = choicesHtml(q.choices);
  if (E.picks[E.pos] !== null) $("exam-choices").querySelectorAll("button")[E.picks[E.pos]].classList.add("picked");
  $("btn-exam-prev").disabled = E.pos === 0;
  $("btn-exam-next").disabled = E.pos === E.items.length - 1;
}

function examPick(i) {
  if (i >= E.items[E.pos].choices.length) return;
  E.picks[E.pos] = i;
  showExamQuestion();
  if (E.pos < E.items.length - 1) setTimeout(() => { E.pos += 1; showExamQuestion(); }, 250);
}
$("exam-choices").addEventListener("click", e => {
  const b = e.target.closest("button[data-choice]");
  if (b) examPick(+b.dataset.choice);
});
$("btn-exam-prev").addEventListener("click", () => { E.pos = Math.max(0, E.pos - 1); showExamQuestion(); });
$("btn-exam-next").addEventListener("click", () => { E.pos = Math.min(E.items.length - 1, E.pos + 1); showExamQuestion(); });
$("btn-exam-finish").addEventListener("click", () => {
  const missing = E.picks.filter(p => p === null).length;
  if (missing && !finishExam.confirmed) {
    finishExam.confirmed = true;
    toast(t("exam_missing", {n: missing}));
    return;
  }
  finishExam();
});

async function finishExam() {
  if ($("exam-run").hidden) return;
  finishExam.confirmed = false;
  clearInterval(E.timer);
  const seconds = Math.round((Date.now() - E.started) / 1000);
  const answers = E.items.map((q, i) => ({id: q.id, correct: E.picks[i] === q.answer_index,
                                          answer: E.picks[i] === null ? "" : q.choices[E.picks[i]]}));
  let result;
  try {
    result = await api("/api/jlpt/exam_result", {level: J.level, answers, seconds});
  } catch (e) { toast(t("exam_not_saved", {e: e.message})); return; }
  $("exam-run").hidden = true;
  $("exam-result").hidden = false;
  const pct = Math.round(100 * result.score / Math.max(1, result.total));
  $("exam-score").textContent = `${result.score} / ${result.total} — ${pct} %`;
  $("exam-verdict").textContent = (pct >= 60 ? t("verdict_good") : pct >= 45 ? t("verdict_close") : t("verdict_work"))
    + t("exam_duration", {n: Math.round(seconds / 60)});
  $("exam-sections").innerHTML = `<tr><th>${t("h_section")}</th><th class="num">${t("h_score")}</th></tr>` +
    Object.entries(result.detail).map(([t, [ok, n]]) => `<tr><td lang="ja">${esc(TYPE_SHORT[t] || t)}</td>
      <td class="num">${ok} / ${n} (${Math.round(100 * ok / n)} %)</td></tr>`).join("");
  const wrong = E.items.map((q, i) => ({q, pick: E.picks[i]})).filter(x => x.pick !== x.q.answer_index);
  $("exam-mistakes").innerHTML = wrong.length ? wrong.map(({q, pick}) => `<div class="mistake">
      <div class="jp" lang="ja">${questionHtml(q.question)}</div>
      <div>${t("your_answer")}<span lang="ja">${pick === null ? "—" : esc(q.choices[pick])}</span> ·
        ${t("good_answer")}<strong lang="ja">${esc(q.answers[0])}</strong></div>
      ${q.full_sentence ? `<div class="muted" lang="ja">${esc(q.full_sentence)}</div>` : ""}
      ${q.translation ? `<div class="tr">${esc(q.translation)}</div>` : ""}
      ${q.explanation ? `<div class="small">${esc(q.explanation).replace(/\n/g, "<br>")}</div>` : ""}
    </div>`).join("") : `<p>${t("no_mistake")}</p>`;
}
$("btn-exam-back").addEventListener("click", () => {
  $("exam-result").hidden = true;
  $("jlpt-home").hidden = false;
  loadJlpt();
});

// ======================================================================
// ---------------- first start ----------------

function showSetup(s) {
  document.body.classList.add("in-setup");
  $("setup").hidden = false;
  document.querySelectorAll("#setup-lang .seg").forEach(b => b.classList.toggle("active", b.dataset.value === LANG));
  $("setup-anki").innerHTML = s.anki_found
    ? `${esc(t("setup_anki_found"))}<br><label class="check"><input type="checkbox" id="setup-anki-use" checked> ${esc(t("setup_anki_use"))}</label>`
    : esc(t("setup_anki_none"));
  const ready = s.ollama && s.model_installed;
  $("setup-model-state").textContent = ready ? t("setup_model_ready", {model: s.model}) : t("setup_model_missing", {model: s.model});
  $("setup-local").checked = !!ready;
}
document.querySelectorAll("#setup-lang .seg").forEach(b => b.addEventListener("click", async () => {
  if (b.dataset.value === LANG) return;
  await api("/api/settings", {language: b.dataset.value}).catch(() => {});
  location.reload();
}));
$("btn-setup-go").addEventListener("click", async () => {
  const level = document.querySelector("#setup-level input:checked")?.value || "N5";
  try {
    const job = await api("/api/setup", {language: LANG, level, anki: !!$("setup-anki-use")?.checked,
                                         local_model: $("setup-local").checked});
    document.body.classList.remove("in-setup");
    $("setup").hidden = true;
    showTab("progress");
    renderFill(job);
    pollFill.was = true;
    setTimeout(pollFill, 1000);
  } catch (e) { toast(e.message); }
});
$("btn-quit").addEventListener("click", async () => {
  await api("/api/quit", {}).catch(() => {});
  document.body.innerHTML = `<p style="padding:40px;text-align:center">✓</p>`;
});

$("lang-select").value = LANG;
$("lang-select").addEventListener("change", async e => {
  try {
    await api("/api/settings", {language: e.target.value});
    location.reload();
  } catch (err) { toast(err.message); }
});

window.JapaneseCoach = {session: S, chat: C, exam: E};  // handy in the browser console, and for tests
loadStatus().then(s => { if (s && s.setup) showSetup(s); });
loadHome();
loadSettings();
api("/api/fill").then(f => { if (f.running) { pollFill.was = true; pollFill(); } else renderFill(f); }).catch(() => {});
