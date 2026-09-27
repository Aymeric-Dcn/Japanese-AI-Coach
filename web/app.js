// Japanese Coach — interface (session, chat with the tutor, progress).
// Talks to server.py through /api/…; the interface text is in French.
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

async function loadStatus() {
  try {
    const s = await api("/api/status");
    const item = (ok, on, off) => `<span class="${ok ? "on" : "off"}">${ok ? on : off}</span>`;
    $("status").innerHTML =
      item(s.ollama && s.model_installed, `Prof : ${esc(s.model)}`, s.ollama ? `${esc(s.model)} non installé` : "Ollama éteint") +
      item(s.anki_sync, "Anki synchronisé", "Anki non synchronisé");
    return s;
  } catch (e) {
    $("status").innerHTML = `<span class="off">Serveur injoignable</span>`;
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
    `<span class="pill">À revoir : <strong>${stats.due_now}</strong></span>`,
    `<span class="pill">Nouveaux disponibles : <strong>${stats.unseen}</strong></span>`,
    `<span class="pill">Aujourd'hui : <strong>${stats.today.done}</strong> faits${stats.today.done ? ` · ${pct} % justes` : ""}</span>`,
    stats.day_streak ? `<span class="pill">Série : <strong>${stats.day_streak}</strong> jour${stats.day_streak > 1 ? "s" : ""}</span>` : "",
  ].join("");
}

const P = {mode: store("mode") || "daily", topics: [], picked: new Set(JSON.parse(store("picked") || "[]"))};
const STATE_LABEL = {passed: "validé", current: "en cours", locked: "🔒 à venir", custom: "hors programme"};

function setMode(mode) {
  P.mode = mode;
  store("mode", mode);
  document.querySelectorAll(".seg").forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
  $("mode-daily").hidden = mode !== "daily";
  $("mode-practice").hidden = mode !== "practice";
  updateStartButton();
}
document.querySelectorAll(".seg").forEach(b => b.addEventListener("click", () => setMode(b.dataset.mode)));

function updateStartButton() {
  const reserve = P.topics.reduce((n, t) => n + t.total, 0);
  $("btn-start").disabled = !reserve || (P.mode === "practice" && !P.picked.size);
}

function renderPicker() {
  const levels = {};
  for (const t of P.topics) {
    if (!t.total) continue;  // nothing to practise yet
    (levels[t.level || "Autres"] = levels[t.level || "Autres"] || []).push(t);
  }
  const html = Object.entries(levels).map(([level, list]) => `<h4>${esc(level)}</h4>` + list.map(t =>
    `<label><input type="checkbox" value="${esc(t.title)}"${P.picked.has(t.title) ? " checked" : ""}>
      ${esc(t.title)} <span class="muted small">(${t.unseen} nouveaux)</span></label>`).join("")).join("");
  $("topic-picker").innerHTML = html || `<p class="muted">Aucun exercice dans la réserve pour l'instant.</p>`;
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
  if (pick === "particle") { $("hard-mode").checked = true; store("hardMode", "1"); }  // « toutes les particules » = sans liste
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
    const names = current.map(t => `<strong>${esc(t.title)}</strong>`).join(" et ");
    $("start-text").innerHTML = !reserve
      ? `La réserve d'exercices est vide : va dans <strong>Progrès → Remplir la réserve</strong>.`
      : (stats.due_now ? `${stats.due_now} exercice${stats.due_now > 1 ? "s" : ""} à revoir, puis des nouveaux` : "Rien à revoir aujourd'hui ; nouveaux exercices")
        + (current.length ? ` sur ${names}.` : ".");
    const empty = current.filter(t => !t.unseen);
    $("daily-empty").hidden = !empty.length || !reserve;
    $("daily-empty").innerHTML = empty.length ? `Plus d'exercices nouveaux pour ${empty.map(t => esc(t.title)).join(", ")}.
      <button class="ghost" id="btn-goto-fill">Remplir la réserve →</button>` : "";
    const goto = $("btn-goto-fill");
    if (goto) goto.onclick = () => showTab("progress");
    renderPicker();
    setMode(P.mode);
  } catch (e) { toast("Impossible de charger les statistiques : " + e.message); }
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
      toast(P.mode === "practice" ? "Rien de nouveau ni à revoir dans ces thèmes." :
        data.stats.unseen ? "Rien à revoir. Choisis au moins 5 nouveaux exercices, ou remplis la réserve." : "Plus rien à faire aujourd'hui : bravo !");
      return;
    }
    Object.assign(S, {queue: data.items, pos: 0, done: 0, firstTry: 0});
    $("session-start").hidden = true;
    $("session-end").hidden = true;
    $("session-run").hidden = false;
    showExercise();
  } catch (e) { toast("Impossible de démarrer la session : " + e.message); }
}

function showExercise() {
  const ex = S.queue[S.pos];
  S.current = ex;
  S.solved = false;
  ex._attempts = ex._attempts || 0;
  const box = $("exo");
  box.classList.remove("ok", "ko");

  const badge = $("exo-status");
  badge.textContent = ex._retry ? "À refaire" : ex.status === "review" ? "Révision" : "Nouveau";
  badge.classList.toggle("review", ex.status === "review" || ex._retry);
  $("exo-topic").textContent = ex.topic;
  $("exo-count").textContent = `${S.pos + 1} / ${S.queue.length}`;
  $("progress-fill").style.width = `${100 * S.pos / S.queue.length}%`;

  const allowed = ex.allowed_answers || [];
  if (ex.cue) {
    $("exo-choices").innerHTML = `Verbe à conjuguer : <span class="ans" lang="ja">${esc(ex.cue)}</span>` +
      (ex.cue_reading ? ` <span class="muted" lang="ja">（${esc(ex.cue_reading)}）</span>` : "") +
      ` <span class="muted small">· réponse en kanji ou en kana</span>`;
  } else {
    $("exo-choices").innerHTML = allowed.length && !$("hard-mode").checked
      ? "Réponses possibles : " + allowed.map(a => `<span class="ans" lang="ja">${esc(a)}</span>`).join("") : "";
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
      aria-label="Réponse" style="width:${width}em">${esc(after ?? "")}`;
  }
  $("exo-reading").textContent = ex.reading || "";
  $("exo-translation").textContent = ex.show_translation ? (ex.translation || "") : "";
  $("exo-new").innerHTML = (ex.new_words || []).length ? `Nouveau : <span lang="ja">${ex.new_words.map(esc).join("、")}</span>` : "";

  $("exo-hint").hidden = true;
  $("exo-hint").textContent = "💡 " + (ex.hint || "");
  $("btn-hint").hidden = !ex.hint;
  $("btn-show").hidden = true;
  $("btn-check").hidden = !!ex.choices;
  $("exo-feedback").hidden = true;
  $("after-actions").hidden = true;
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
  $("exo").classList.toggle("ok", ok);
  $("exo").classList.toggle("ko", !ok);
  await record(ok, ex.choices[i]);
  if (!ok) requeue(ex);
  const full = ex.full_sentence ? `<br><span lang="ja">${esc(ex.full_sentence)}</span>` : "";
  S.solved = true;
  $("exo-feedback").hidden = false;
  $("exo-feedback").innerHTML = solutionHtml(ex, (ok ? "✓ <strong>Correct !</strong>" :
    `✗ Réponse : <strong lang="ja">${esc(ex.answers[0])}</strong>`) + full);
  $("btn-check").hidden = true;
  $("after-actions").hidden = false;
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
  S.done += 1;
  if (correct) S.firstTry += 1;
  try {
    const data = await api("/api/answer", {id: ex.id, correct, answer});
    renderSummary(data.stats);
    ex._schedule = data.schedule;
    return data.schedule;
  } catch (e) {
    toast("Réponse non enregistrée : " + e.message);
    return null;
  }
}

function nextReviewText(schedule) {
  if (!schedule) return "";
  const d = schedule.interval;
  return `<div class="next-review">Prochaine révision : ${d <= 1 ? "demain" : `dans ${d} jours`}</div>`;
}

function solutionHtml(ex, message) {
  const schedule = ex._retry ? null : ex._schedule;
  const others = ex.answers.length > 1 ? `<br>Réponses acceptées : <span lang="ja">${ex.answers.map(esc).join(" / ")}</span>` : "";
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
    solve(solutionHtml(ex, "✓ <strong>Correct !</strong>"));
  } else {
    fb.innerHTML = "✗ Pas tout à fait. Réessaie, demande un indice ou affiche la réponse.";
    $("btn-show").hidden = false;
    requeue(ex);
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
  solve(solutionHtml(ex, `Réponse : <strong lang="ja">${esc(ex.answers[0])}</strong>`));
}

function solve(html) {
  S.solved = true;
  field().readOnly = true;
  $("exo-feedback").hidden = false;
  $("exo-feedback").innerHTML = html;
  $("btn-show").hidden = true;
  $("btn-check").hidden = true;
  $("after-actions").hidden = false;
  $("btn-next").focus();
}

function next() {
  S.pos += 1;
  if (S.pos < S.queue.length) return showExercise();
  $("progress-fill").style.width = "100%";
  $("session-run").hidden = true;
  $("session-end").hidden = false;
  const st = S.lastStats;
  $("end-text").innerHTML = `${S.done} exercice${S.done > 1 ? "s" : ""}, ${S.firstTry} juste${S.firstTry > 1 ? "s" : ""} du premier coup.` +
    (st ? `<br><span class="muted">Demain : ${st.due_tomorrow} à revoir · ${st.unseen} nouveaux encore disponibles.</span>` : "");
  $("btn-more").hidden = !(st && st.unseen);
}

$("btn-start").addEventListener("click", () => startSession());
$("btn-more").addEventListener("click", () => startSession(5));
$("btn-home").addEventListener("click", () => { $("session-end").hidden = true; $("session-start").hidden = false; loadHome(); });
$("btn-check").addEventListener("click", check);
$("btn-show").addEventListener("click", showAnswer);
$("btn-next").addEventListener("click", next);
$("btn-hint").addEventListener("click", () => { $("exo-hint").hidden = false; });
$("btn-readings").addEventListener("click", e => {
  const hidden = document.body.classList.toggle("hide-readings");
  e.target.textContent = hidden ? "Afficher la lecture" : "Masquer la lecture";
  store("hideReadings", hidden ? "1" : "0");
});
$("hard-mode").checked = store("hardMode") === "1";
$("hard-mode").addEventListener("change", e => store("hardMode", e.target.checked ? "1" : "0"));
if (store("hideReadings") === "1") {
  document.body.classList.add("hide-readings");
  $("btn-readings").textContent = "Afficher la lecture";
}
$("btn-ask").addEventListener("click", () => {
  const ex = S.current;
  if (C.mode !== "prof") setChatMode("prof");
  setChatContext({
    sentence: ex.sentence || ex.question, full_sentence: ex.full_sentence, answers: ex.answers, cue: ex.cue,
    topic: ex.topic, choices: ex.choices,
    translation: ex.translation, explanation: ex.explanation, given: ex._given || "",
  });
  showTab("chat");
});

document.addEventListener("keydown", e => {
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
const CHAT_INTRO = {
  prof: `Sensei est prêt. Pose une question de grammaire, demande des exemples, ou écris une phrase en japonais pour la faire corriger.`,
  conversation: `Conversation en japonais simple : Sensei répond en japonais avec la traduction, et corrige tes fautes au passage. Choisis une situation, puis clique sur « Commencer » ou écris directement.`,
  quiz: `Sensei t'interroge sur tes points faibles, une question à la fois. Clique sur « Commencer ».`,
};

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
  div.setAttribute("lang", "fr");
  div.innerHTML = role === "user" ? esc(text).replace(/\n/g, "<br>") : markdown(text);
  $("messages").appendChild(div);
  $("messages").scrollTop = $("messages").scrollHeight;
  return div;
}

function emptyChat() {
  const start = C.mode === "prof" ? "" : `<br><button class="primary chat-start" id="btn-chat-start">Commencer</button>`;
  $("messages").innerHTML = `<div class="empty-chat">${CHAT_INTRO[C.mode]}${start}</div>`;
  const b = $("btn-chat-start");
  if (b) b.onclick = () => send(C.mode === "quiz" ? "Interroge-moi !" : "よろしくお願いします。");
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
  $("chat-context-text").innerHTML = ex ? `Question sur : <span lang="ja">${esc(ex.full_sentence || ex.sentence)}</span>` : "";
  if (ex) $("chat-input").value = ex.given && !ex.answers.some(a => norm(a) === norm(ex.given))
    ? `Pourquoi « ${ex.answers[0]} » et pas « ${ex.given} » ?` : "Pourquoi cette réponse ?";
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
          refs.textContent = "Références : " + msg.refs.join(" · ");
          bubble.after(refs);
        }
        if (msg.delta) {
          answer += msg.delta;
          bubble.innerHTML = markdown(answer);
          $("messages").scrollTop = $("messages").scrollHeight;
        }
      }
    }
    if (!answer) throw new Error("Réponse vide.");
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
      card(s.today.done, "faits aujourd'hui"),
      card(s.due_tomorrow, "à revoir demain"),
      card(s.day_streak, "jours d'affilée"),
      card(s.learning, "exercices en cours"),
      card(s.mastered, "maîtrisés (≥ 21 jours)"),
      card(`${pct} %`, `justes du premier coup (${s.all_time.done} au total)`),
    ].join("");
    await loadProgramme();
    $("weak-card").hidden = !s.weakest.length;
    $("weak-list").innerHTML = s.weakest.map(w =>
      `<li>${esc(w.topic)} : ${Math.round(100 * w.correct / w.done)} % de réussite (${w.done} réponses)</li>`).join("");
  } catch (e) { toast("Impossible de charger les statistiques : " + e.message); }
}

async function loadProgramme() {
  const data = await api("/api/topics");
  P.topics = data.topics;
  $("topics-table").innerHTML = `<tr><th></th><th>Thème</th><th>État</th><th class="num">Réussite</th>
      <th class="num">Nouveaux / total</th><th></th></tr>` +
    P.topics.map(t => {
      const rate = t.answers ? `${Math.round(100 * t.rate)} % <span class="muted small">(${t.answers})</span>` : "—";
      const action = t.state === "custom" ? "" : t.flagged
        ? `<button data-known="0" data-title="${esc(t.title)}">Annuler</button>`
        : t.state !== "passed" ? `<button data-known="1" data-title="${esc(t.title)}" title="Le thème compte comme validé">Je maîtrise déjà</button>` : "";
      return `<tr><td class="level">${esc(t.level)}</td><td>${esc(t.title)}</td>
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

// ---------------- filling the reserve ----------------

function renderFill(f) {
  document.querySelectorAll(".job-log").forEach(log => {
    log.hidden = !f.log.length;
    log.textContent = (f.title ? `— ${f.title} (${f.started || ""}${f.finished ? " → " + f.finished : ""}) —\n` : "") + f.log.join("\n");
    log.scrollTop = log.scrollHeight;
  });
  $("btn-fill").disabled = f.running;
  $("btn-fill").textContent = f.running ? `${f.title || "Remplissage"} en cours…` : "Remplir la réserve";
  $("btn-fill-stop").hidden = !f.running;
  $("btn-jlpt-fill").disabled = f.running;
  $("jlpt-fill-state").textContent = f.running ? `${f.title} en cours… (tu peux continuer à travailler)` : "";
}

async function pollFill() {
  try {
    const f = await api("/api/fill");
    renderFill(f);
    if (f.running) { setTimeout(pollFill, 1500); return; }
    if (pollFill.was) {
      toast(`${f.title || "Réserve"} : ${f.added ?? 0} exercice(s) ajouté(s).`);
      loadHome(); loadProgramme();
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
    if (!o.lexicon) notes.push("Niveaux approximatifs : lance anki_sync.py et/ou jlpt_data.py pour connaître le niveau des mots.");
    if (!o.kanji) notes.push("Pas de fiches kanji (data/kanji.json) : pas de questions 表記.");
    $("jlpt-note").textContent = "Nouvelles / total par type de question. " + notes.join(" ");
    if (!J.types.size) o.types.forEach(t => J.types.add(t.type));
    $("jlpt-type-picker").innerHTML = o.types.map(t => `<label><input type="checkbox" value="${t.type}"${J.types.has(t.type) ? " checked" : ""}>
      <span lang="ja">${esc(t.label)}</span> <span class="muted small">(${t.total})</span></label>`).join("");
    const plan = o.types.filter(t => t.exam).map(t => `${TYPE_SHORT[t.type]} ${t.exam}`).join(" · ");
    const total = o.types.reduce((n, t) => n + t.exam, 0);
    $("jlpt-exam-plan").textContent = `${total} questions en ${total} minutes, sans correction avant la fin : ${plan}. ` +
      "Format inspiré du JLPT (partie connaissances de la langue, sans compréhension écrite).";
    $("btn-jlpt-exam").disabled = !o.types.some(t => t.total);
    $("btn-jlpt-practice").disabled = !o.types.some(t => t.total);
    $("jlpt-history").innerHTML = o.exams.length ? `<table class="topics"><tr><th>Date</th><th>Niveau</th><th class="num">Score</th><th class="num">Durée</th></tr>` +
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
    if (!data.items.length) return toast("Aucune question pour ces types : génère-en d'abord.");
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
    if (!data.items.length) return toast("Pas assez de questions : génère-en d'abord.");
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
  $("exam-count").textContent = `Question ${E.pos + 1} / ${E.items.length} · ${E.picks.filter(p => p !== null).length} répondues`;
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
    toast(`${missing} question(s) sans réponse. Clique encore sur « Terminer » pour rendre ta copie.`);
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
  } catch (e) { toast("Résultat non enregistré : " + e.message); return; }
  $("exam-run").hidden = true;
  $("exam-result").hidden = false;
  const pct = Math.round(100 * result.score / Math.max(1, result.total));
  $("exam-score").textContent = `${result.score} / ${result.total} — ${pct} %`;
  $("exam-verdict").textContent = (pct >= 60 ? "Très bien : niveau atteint sur cette partie. " : pct >= 45 ? "Pas loin : encore un effort. " : "À retravailler. ")
    + `Durée : ${Math.round(seconds / 60)} min. Tes erreurs reviendront dans les révisions.`;
  $("exam-sections").innerHTML = `<tr><th>Section</th><th class="num">Score</th></tr>` +
    Object.entries(result.detail).map(([t, [ok, n]]) => `<tr><td lang="ja">${esc(TYPE_SHORT[t] || t)}</td>
      <td class="num">${ok} / ${n} (${Math.round(100 * ok / n)} %)</td></tr>`).join("");
  const wrong = E.items.map((q, i) => ({q, pick: E.picks[i]})).filter(x => x.pick !== x.q.answer_index);
  $("exam-mistakes").innerHTML = wrong.length ? wrong.map(({q, pick}) => `<div class="mistake">
      <div class="jp" lang="ja">${questionHtml(q.question)}</div>
      <div>Ta réponse : <span lang="ja">${pick === null ? "—" : esc(q.choices[pick])}</span> ·
        Bonne réponse : <strong lang="ja">${esc(q.answers[0])}</strong></div>
      ${q.full_sentence ? `<div class="muted" lang="ja">${esc(q.full_sentence)}</div>` : ""}
      ${q.translation ? `<div class="tr">${esc(q.translation)}</div>` : ""}
      ${q.explanation ? `<div class="small">${esc(q.explanation).replace(/\n/g, "<br>")}</div>` : ""}
    </div>`).join("") : "<p>Aucune erreur, bravo !</p>";
}
$("btn-exam-back").addEventListener("click", () => {
  $("exam-result").hidden = true;
  $("jlpt-home").hidden = false;
  loadJlpt();
});

// ======================================================================
window.JapaneseCoach = {session: S, chat: C, exam: E};  // handy in the browser console, and for tests
loadStatus();
loadHome();
loadSettings();
api("/api/fill").then(f => { if (f.running) { pollFill.was = true; pollFill(); } else renderFill(f); }).catch(() => {});
