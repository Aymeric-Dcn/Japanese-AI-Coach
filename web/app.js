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

async function loadHome() {
  try {
    const stats = await api("/api/stats");
    renderSummary(stats);
    const select = $("topic-select");
    const current = select.value;
    select.innerHTML = `<option value="">Tous les thèmes (mélangés)</option>` +
      stats.topics.map(t => `<option value="${esc(t.topic)}">${esc(t.topic)} (${t.unseen} nouveaux)</option>`).join("");
    select.value = current;
    if (!stats.topics.length) {
      $("start-text").innerHTML = `La réserve d'exercices est vide. Remplis-la depuis le terminal, par exemple :<br>
        <code>python make_exercises.py --preset ni-de --known --max-unknown 1 --count 30 --save</code>`;
      $("btn-start").disabled = true;
    } else {
      $("start-text").textContent = stats.due_now
        ? `${stats.due_now} exercice${stats.due_now > 1 ? "s" : ""} à revoir aujourd'hui, puis des nouveaux.`
        : "Rien à revoir aujourd'hui : place aux nouveaux exercices.";
      $("btn-start").disabled = false;
    }
  } catch (e) { toast("Impossible de charger les statistiques : " + e.message); }
}

async function startSession(newCount) {
  const topic = $("topic-select").value;
  const n = newCount ?? $("new-select").value;
  try {
    const data = await api(`/api/session?new=${n}&topic=${encodeURIComponent(topic)}`);
    renderSummary(data.stats);
    if (!data.items.length) {
      toast(data.stats.unseen ? "Rien à revoir. Choisis au moins 5 nouveaux exercices." : "Plus rien à faire aujourd'hui : bravo !");
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
  $("exo-choices").innerHTML = allowed.length && ex.kind !== "conjugation"
    ? "Réponses possibles : " + allowed.map(a => `<span lang="ja">${esc(a)}</span>`).join("") : "";

  const [before, after] = ex.sentence.split(BLANK);
  const width = Math.max(4, (ex.answers[0] || "").length + 2);
  $("exo-sentence").innerHTML = `${esc(before)}<input id="answer" lang="ja" autocomplete="off" spellcheck="false"
    aria-label="Réponse" style="width:${width}em">${ex.cue ? `<span class="cue">（${esc(ex.cue)}）</span>` : ""}${esc(after ?? "")}`;
  $("exo-reading").textContent = ex.reading || "";
  $("exo-translation").textContent = ex.show_translation ? (ex.translation || "") : "";
  $("exo-new").innerHTML = (ex.new_words || []).length ? `Nouveau : <span lang="ja">${ex.new_words.map(esc).join("、")}</span>` : "";

  $("exo-hint").hidden = true;
  $("exo-hint").textContent = "💡 " + (ex.hint || "");
  $("btn-hint").hidden = !ex.hint;
  $("btn-show").hidden = true;
  $("btn-check").hidden = false;
  $("exo-feedback").hidden = true;
  $("after-actions").hidden = true;
  $("answer").focus();
}

function field() { return $("answer"); }

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
if (store("hideReadings") === "1") {
  document.body.classList.add("hide-readings");
  $("btn-readings").textContent = "Afficher la lecture";
}
$("btn-ask").addEventListener("click", () => {
  const ex = S.current;
  setChatContext({
    sentence: ex.sentence, full_sentence: ex.full_sentence, answers: ex.answers, cue: ex.cue,
    translation: ex.translation, explanation: ex.explanation, given: ex._given || "",
  });
  showTab("chat");
});

document.addEventListener("keydown", e => {
  if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;  // Enter confirms Japanese IME input
  if (!$("tab-session").classList.contains("active") || $("session-run").hidden) return;
  if (e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
  if (e.target.tagName === "BUTTON" && e.target.id !== "btn-next") return;
  e.preventDefault();
  if (S.solved) next(); else check();
});

// ======================================================================
// Chat with the tutor
// ======================================================================

const C = {id: store("conversation") || "main", loaded: false, busy: false, context: null};

function markdown(text) {
  // Tiny, safe renderer: escape first, then **bold**, `code`, lists and paragraphs.
  const lines = esc(text).split("\n");
  let html = "", list = null, para = [];
  const inline = s => s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
  const flushPara = () => { if (para.length) { html += `<p>${para.map(inline).join("<br>")}</p>`; para = []; } };
  const flushList = () => { if (list) { html += `<${list.tag}>${list.items.map(i => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`; list = null; } };
  for (const line of lines) {
    const bullet = line.match(/^\s*[-*・]\s+(.*)/), num = line.match(/^\s*\d+[.)]\s+(.*)/);
    if (bullet || num) {
      flushPara();
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tag !== tag) { flushList(); list = {tag, items: []}; }
      list.items.push((bullet || num)[1]);
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
  $("messages").innerHTML = `<div class="empty-chat">Sensei est prêt. Pose une question de grammaire,
    demande des exemples, ou écris une phrase en japonais pour la faire corriger.</div>`;
}

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
      body: JSON.stringify({conversation: C.id, message: text, exercise: context}),
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
$("chips").addEventListener("click", e => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  $("chat-input").value = chip.dataset.text;
  $("chat-input").focus();
  if (!chip.dataset.text.endsWith(" ")) $("composer").requestSubmit();
});
$("btn-new-chat").addEventListener("click", () => {
  C.id = "c-" + Date.now();
  store("conversation", C.id);
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
    $("topics-table").innerHTML = `<tr><th>Thème</th><th class="num">Total</th><th class="num">Pas encore vus</th></tr>` +
      (s.topics.length ? s.topics.map(t => `<tr><td>${esc(t.topic)}</td><td class="num">${t.total}</td><td class="num">${t.unseen}</td></tr>`).join("")
        : `<tr><td colspan="3" class="muted">Aucun exercice pour l'instant.</td></tr>`);
    $("weak-card").hidden = !s.weakest.length;
    $("weak-list").innerHTML = s.weakest.map(w =>
      `<li>${esc(w.topic)} : ${Math.round(100 * w.correct / w.done)} % de réussite (${w.done} réponses)</li>`).join("");
  } catch (e) { toast("Impossible de charger les statistiques : " + e.message); }
}

// ======================================================================
window.JapaneseCoach = {session: S, chat: C};  // handy in the browser console, and for tests
loadStatus();
loadHome();
