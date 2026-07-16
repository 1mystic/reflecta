// Reflecta - live quiz flow. Talks to the FastAPI backend.
//
// This frontend is a static SPA served BY the same FastAPI process it talks to
// (see api/main.py's StaticFiles mount) - that's why there's no build step and no
// separate frontend server: uvicorn/gunicorn on :8000 serves both the API and this
// file. The correct base URL is therefore always same-origin. The one exception is
// opening this file directly (`file://`), e.g. while editing - there is no "origin"
// to be same as, so fall back to localhost:8000 explicitly.
//
// If you *do* run this file from a separate dev server (a bundler, VS Code Live
// Server, etc.) on a different port, requests will silently go to that dev server
// instead of the API and fail (commonly as a 404 or 405, since most static dev
// servers don't implement POST) - always open http://localhost:8000 directly, or set
// window.REFLECTA_API_BASE before this script loads if you truly need to override it.
const API = window.REFLECTA_API_BASE ?? (location.protocol === "file:" ? "http://localhost:8000" : "");
const $ = (id) => document.getElementById(id);
const pct = (x) => (x == null ? "–" : Math.round(x * 100) + "%");

// Opaque, client-only learner id (server-minted UUID, no PII) - persisted so mastery
// can be shown to accumulate across repeat quizzes. "Delete my responses" (below) also
// clears it, so erasure means forgetting the device link too, not just one session.
const LEARNER_KEY = "reflecta_learner_id";
function getLearnerId() { return localStorage.getItem(LEARNER_KEY); }
function setLearnerId(id) { if (id) localStorage.setItem(LEARNER_KEY, id); }
function clearLearnerId() { localStorage.removeItem(LEARNER_KEY); }

// FastAPI error bodies vary in shape: HTTPException -> {detail: "string"};
// Pydantic 422 validation errors -> {detail: [{loc, msg, type}, ...]}. Normalize both
// to a readable string instead of letting `[object Object]` reach the user.
async function readApiError(res) {
  let body;
  try { body = await res.json(); } catch { return `API ${res.status}`; }
  const d = body && body.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d.map((e) => `${(e.loc || []).slice(-1)[0] || "field"}: ${e.msg}`).join("; ");
  }
  return `API ${res.status}`;
}

// [text, tone] where tone in {good, mid, low} drives the tag colour
function setTag(id, spec) {
  const el = $(id);
  if (!el || !spec) { if (el) el.textContent = ""; return; }
  el.textContent = spec[0];
  el.className = "tag tag-" + spec[1];
}

const TIMING_META = {
  fast_correct: { label: "Fluent", color: "#8faa78" },
  slow_correct: { label: "Effortful", color: "#b17a50" },
  fast_wrong:   { label: "Confident miss", color: "#e2a25c" },
  slow_wrong:   { label: "Struggling", color: "#cf7b52" },
};

// ── reactive face: each emotion (from the backend's face_emotion) maps to a mouth + brow
// shape. viewBox is 0 0 200 200; eyes are fixed, mouth/brows carry the expression. Colours
// come from CSS via the container's data-emotion attribute (warm palette, not hardcoded). ──
const FACE = {
  calm:          { label: "Calm",          note: "the model is forming its read on you",
    mouth: "M70 130 Q100 140 130 130", browL: "M62 70 Q73 67 84 70", browR: "M116 70 Q127 67 138 70" },
  flow:          { label: "In flow",       note: "you're moving well - answers landing",
    mouth: "M68 126 Q100 154 132 126", browL: "M62 69 Q73 66 84 69", browR: "M116 69 Q127 66 138 69" },
  confident:     { label: "Confident",     note: "high mastery and the model is sure of it",
    mouth: "M70 128 Q100 148 130 128", browL: "M62 69 Q73 65 84 68", browR: "M116 68 Q127 65 138 69" },
  confused:      { label: "Not transferring", note: "you know the phrasing, not yet the idea",
    mouth: "M70 132 Q85 123 100 132 Q115 141 130 132", browL: "M62 66 Q73 62 84 68", browR: "M116 70 Q127 71 138 72" },
  overconfident: { label: "Overconfident", note: "answering fast and sure, but missing",
    mouth: "M70 134 Q100 134 130 120", browL: "M62 72 Q73 70 84 71", browR: "M116 64 Q127 60 138 63" },
  struggling:    { label: "Struggling",    note: "slow and off - this topic is fighting back",
    mouth: "M70 138 Q100 120 130 138", browL: "M62 66 Q73 71 84 74", browR: "M116 74 Q127 71 138 66" },
};

function faceMarkup(prefix) {
  return `<svg viewBox="0 0 200 200" class="face-svg" aria-hidden="true">
    <circle class="face-bg" cx="100" cy="100" r="94"/>
    <circle class="face-eye" cx="74" cy="90" r="7"/>
    <circle class="face-eye" cx="126" cy="90" r="7"/>
    <path class="face-brow" id="${prefix}-brow-l"/>
    <path class="face-brow" id="${prefix}-brow-r"/>
    <path class="face-mouth" id="${prefix}-mouth"/>
  </svg>`;
}

// apply an emotion to a face: set the mouth/brow paths and the container tone (for colour)
function applyFace(cardId, prefix, emotion) {
  const f = FACE[emotion] || FACE.calm;
  const set = (id, d) => { const el = $(id); if (el) el.setAttribute("d", d); };
  set(`${prefix}-mouth`, f.mouth);
  set(`${prefix}-brow-l`, f.browL);
  set(`${prefix}-brow-r`, f.browR);
  const card = $(cardId);
  if (card) {
    card.setAttribute("data-emotion", emotion);
    card.classList.remove("face-pulse");
    void card.offsetWidth;              // restart the pulse animation on each update
    card.classList.add("face-pulse");
  }
  return f;
}

let state = {
  sessionId: null, goal: "", questions: [], idx: 0,
  answers: {}, selected: null, questionStart: 0, lastVitals: null,
};

const PAGE_TITLE = { start: "Take Quiz", quiz: "Quiz", vitals: "Cognitive Vitals",
                     results: "Your Reflection", lab: "Model Lab",
                     reports: "Reports", privacy: "Privacy", architecture: "Architecture" };
const SCREENS = ["start", "quiz", "vitals", "results", "lab", "reports", "privacy", "architecture"];

// The true marketing landing page (#landing, no sidebar) and the app shell
// (#app-shell, sidebar + screens) are separate top-level views - "Get started" enters
// the app shell; the sidebar's logo returns to the landing page.
function enterApp() {
  $("landing").classList.add("hidden");
  $("app-shell").classList.remove("hidden");
  show("start");
}

function showLanding() {
  $("app-shell").classList.add("hidden");
  $("landing").classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function show(screen) {
  SCREENS.forEach((s) => $(`screen-${s}`).classList.toggle("hidden", s !== screen));
  document.getElementById("page-title").textContent = PAGE_TITLE[screen] || "Reflecta";
  const view = screen === "quiz" ? "start" : screen;
  document.querySelectorAll(".nav-item").forEach((el) => el.classList.remove("active"));
  document.querySelector('.nav-item[data-view="' + view + '"]')?.classList.add("active");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ── start ──
async function startQuiz() {
  const btn = $("start-btn");
  btn.disabled = true;
  btn.textContent = "Preparing… (new topics can take a minute)";
  try {
    const res = await fetch(`${API}/api/quiz/start`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        goal: $("goal").value.trim() || "data science interview",
        // defensive fallback: never send NaN (JSON.stringify silently turns it into
        // null, which reads as a confusing "not a valid integer" 422 from the API)
        n_questions: parseInt($("nq").value, 10) || 12,
        consent: $("consent").checked,
        learner_id: getLearnerId() || undefined,
      }),
    });
    if (!res.ok) {
      // surface the server's message (e.g. how to enable open-topic generation)
      throw new Error(await readApiError(res));
    }
    const data = await res.json();
    setLearnerId(data.learner_id);
    state = { sessionId: data.session_id, goal: data.goal, questions: data.questions,
              idx: 0, answers: {}, selected: null, questionStart: 0, lastVitals: null };
    resetVitals();
    show("quiz");
    renderQuestion();
  } catch (e) {
    alert(e.message || ("Couldn't reach the Reflecta API.\nStart it with:  uvicorn api.main:app --reload\n\n" + e));
  } finally {
    btn.disabled = false; btn.textContent = "Start quiz";
  }
}

// ── quiz ──
function renderQuestion() {
  const q = state.questions[state.idx];
  const n = state.questions.length;
  $("progress-fill").style.width = `${(state.idx / n) * 100}%`;
  $("q-count").textContent = `Question ${state.idx + 1} of ${n}`;
  $("q-concept").textContent = q.concept.replace(/_/g, " ");
  $("q-stem").textContent = q.stem;

  const box = $("options");
  box.innerHTML = "";
  state.selected = null;
  Object.entries(q.options).forEach(([letter, text]) => {
    const el = document.createElement("button");
    el.className = "option";
    el.innerHTML = `<span class="letter">${letter}</span><span>${text}</span>`;
    el.addEventListener("click", () => {
      state.selected = letter;
      [...box.children].forEach((c) => c.classList.remove("selected"));
      el.classList.add("selected");
      $("next-btn").disabled = false;
    });
    box.appendChild(el);
  });

  $("confidence").value = 50;
  $("conf-val").textContent = "50%";
  $("next-btn").disabled = true;
  const isLast = state.idx === n - 1;
  $("next-btn").textContent = isLast ? "Finish ✓" : "Next →";
  // reveal the one-line reflection prompt only on the final question
  $("reflect-block").classList.toggle("hidden", !isLast);
  state.questionStart = performance.now();
}

async function recordAndNext() {
  const q = state.questions[state.idx];
  const elapsed = (performance.now() - state.questionStart) / 1000;
  state.answers[q.id] = {
    question_id: q.id,
    chosen_letter: state.selected,
    response_time: Math.round(elapsed * 100) / 100,
    confidence: parseInt($("confidence").value, 10) / 100,
  };
  const isLast = state.idx >= state.questions.length - 1;
  if (isLast) {
    // fetch the final vitals snapshot BEFORE submit pops the pending session, so the
    // Cognitive Vitals screen reflects the whole quiz; then grade + submit.
    await tickVitals();
    submitQuiz();
  } else {
    tickVitals();          // fire-and-forget: next question renders instantly
    state.idx += 1;
    renderQuestion();
  }
}

// ── live cognitive vitals: grade answers-so-far server-side and animate the face + meters.
// The endpoint returns ONLY aggregate belief-state signals (never the correct answer), so
// this cannot be used to cheat. ──
async function tickVitals() {
  if (!state.sessionId) return;
  try {
    const res = await fetch(`${API}/api/quiz/answer`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, answers: Object.values(state.answers) }),
    });
    if (!res.ok) return;              // vitals are a nice-to-have; never block the quiz
    const v = await res.json();
    state.lastVitals = v;
    renderVitals(v);
  } catch { /* offline / transient: leave the last shown vitals in place */ }
}

function resetVitals() {
  state.lastVitals = null;
  applyFace("qz-vitals", "qz", "calm");
  $("qz-emotion").textContent = FACE.calm.label;
  $("qz-note").textContent = FACE.calm.note;
  $("qz-certainty").style.width = "0%";
  $("qz-theta").textContent = "0.00";
  $("qz-mastery").textContent = "–";
  $("qz-streak").textContent = "0";
}

function renderVitals(v) {
  const f = FACE[v.emotion] || FACE.calm;

  // compact strip on the quiz screen
  applyFace("qz-vitals", "qz", v.emotion);
  $("qz-emotion").textContent = f.label;
  $("qz-note").textContent = f.note;
  $("qz-certainty").style.width = pct(v.certainty);
  $("qz-theta").textContent = v.theta.toFixed(2);
  $("qz-mastery").textContent = pct(v.mastery);
  $("qz-streak").textContent = v.streak;

  // full vitals screen
  const empty = $("vt-empty"); if (empty) empty.classList.add("hidden");
  applyFace("vt-card", "vt", v.emotion);
  $("vt-emotion").textContent = f.label;
  setTag("vt-emotion-tag", [f.note, v.emotion === "confident" || v.emotion === "flow"
    ? "good" : v.emotion === "struggling" ? "low" : "mid"]);
  const deg = Math.round(v.certainty * 360);
  $("vt-ring").style.background = `conic-gradient(var(--brown) ${deg}deg, var(--line) ${deg}deg)`;
  $("vt-certainty-val").textContent = pct(v.certainty);
  $("vt-theta").textContent = v.theta.toFixed(2);
  $("vt-mastery").textContent = pct(v.mastery);

  // move the marker on the ability curve: x from theta (clamped to the plotted range),
  // y from mastery so the dot rides the sigmoid. Matches the polyline geometry above.
  const th = Math.max(-4, Math.min(4, v.theta));
  const cx = 10 + (th + 4) * 19.75;
  const cy = 102.4 - v.mastery * 86.8;
  const dot = $("vt-curve-dot"), guide = $("vt-curve-guide");
  if (dot) { dot.setAttribute("cx", cx.toFixed(1)); dot.setAttribute("cy", cy.toFixed(1)); }
  if (guide) guide.style.transform = `translateX(${(cx - 89).toFixed(1)}px)`;

  // calibration (running): show the gap magnitude + over/under direction
  const dir = v.calibration && v.calibration.direction;
  if (dir == null) { $("vt-calib").textContent = "–"; setTag("vt-calib-tag", null); }
  else {
    $("vt-calib").textContent = pct(Math.abs(dir));
    setTag("vt-calib-tag", dir > 0.08 ? ["overconfident", "low"]
      : dir < -0.08 ? ["underconfident", "mid"] : ["well calibrated", "good"]);
  }

  // timing quadrants (reuse the results-screen meta/colours)
  const timing = $("vt-timing"); timing.innerHTML = "";
  Object.entries(TIMING_META).forEach(([k, meta]) => {
    const val = (v.timing || {})[k] || 0;
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `<span class="bar-label">${meta.label}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${pct(val)};background:${meta.color}"></span></span>`;
    timing.appendChild(row);
  });

  // per-concept mastery, with a transfer flag where the reworded probe dropped accuracy
  const cbox = $("vt-concepts"); cbox.innerHTML = "";
  const concepts = v.per_concept || {};
  const transfer = v.transfer || {};
  const keys = Object.keys(concepts);
  if (!keys.length) cbox.innerHTML = `<span class="muted">Per-concept mastery appears once a concept has been probed.</span>`;
  keys.forEach((c) => {
    const m = concepts[c].mastery;
    const t = transfer[c];
    const flag = (t != null && t >= 0.4) ? ` <span class="tag tag-low vt-flag">reworded -${pct(t)}</span>` : "";
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `<span class="bar-label">${c.replace(/_/g, " ")}${flag}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${pct(m)}"></span></span>`;
    cbox.appendChild(row);
  });
}

// ── reflection history: stored client-side only (localStorage), never sent to the
// server beyond the original quiz submission. Lets "Reflection" in the sidebar show
// past quizzes from this browser, not just the one just taken. ──
const HISTORY_KEY = "reflecta_reflection_history";
const HISTORY_MAX = 20;

function getReflectionHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY)) || []; }
  catch { return []; }
}

function saveReflectionToHistory(submitResponse) {
  // embed each graded item's stem now, while state.questions still has it, so a
  // stored entry is fully self-contained and renders correctly after a page reload
  const graded = (submitResponse.graded || []).map((g) => ({
    ...g, stem: state.questions.find((x) => x.id === g.question_id)?.stem || g.question_id,
  }));
  const entry = {
    timestamp: new Date().toISOString(),
    goal: submitResponse.analysis.goal,
    score: submitResponse.score,
    analysis: submitResponse.analysis,
    graded,
    history: submitResponse.history || null,
  };
  const hist = [entry, ...getReflectionHistory()].slice(0, HISTORY_MAX);
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(hist)); } catch { /* storage full/blocked: skip silently */ }
  return entry;
}

function renderHistoryList(activeTimestamp) {
  const card = $("history-card");
  const list = $("history-list");
  const hist = getReflectionHistory();
  if (!hist.length) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");
  list.innerHTML = "";
  hist.forEach((entry) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "history-item" + (entry.timestamp === activeTimestamp ? " active" : "");
    const date = new Date(entry.timestamp).toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
    btn.innerHTML =
      `<div><div class="hi-goal">${entry.goal}</div><div class="hi-date">${date}</div></div>` +
      `<div class="hi-score">${pct(entry.score)}</div>`;
    btn.addEventListener("click", () => {
      renderResults(entry);
      hasReflection = true;
      show("results");
    });
    list.appendChild(btn);
  });
}

// feature C: render Claude-extracted signals from the learner's free-text reflection.
// Absent (no key, skipped, or a stored history entry) -> the whole card stays hidden.
function renderTextSignals(sig) {
  const card = $("signals-card");
  if (!sig) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");
  $("signals-summary").textContent = sig.summary || "";
  setTag("signals-conf", sig.confidence == null ? null
    : sig.confidence >= 0.66 ? ["sounds confident", "good"]
    : sig.confidence >= 0.33 ? ["mixed confidence", "mid"] : ["sounds unsure", "low"]);
  setTag("signals-hedge", sig.hedging ? ["hedging language", "mid"] : ["direct language", "good"]);
  const flags = $("signals-flags"); flags.innerHTML = "";
  (sig.misconception_flags || []).forEach((f) => {
    const el = document.createElement("span");
    el.className = "chip"; el.textContent = f;
    flags.appendChild(el);
  });
}

async function submitQuiz() {
  const btn = $("next-btn");
  btn.disabled = true; btn.textContent = "Analyzing…";
  try {
    const res = await fetch(`${API}/api/quiz/submit`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.sessionId,
        answers: Object.values(state.answers),
        reflection_text: ($("reflect-text").value || "").trim() || undefined,
      }),
    });
    if (!res.ok) throw new Error(await readApiError(res));
    const submitResponse = await res.json();
    const savedEntry = saveReflectionToHistory(submitResponse);
    renderResults({ ...submitResponse, timestamp: savedEntry.timestamp });
    hasReflection = true;
    show("results");
  } catch (e) {
    alert("Submission failed.\n\n" + (e.message || e));
    btn.disabled = false;
  }
}

// ── results: growth trend across this device's past quizzes ──
function renderGrowth(history) {
  const card = $("growth-card");
  if (!history || history.n_sessions < 2) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");

  const first = history.readiness_trend[0];
  const last = history.readiness_trend[history.readiness_trend.length - 1];
  const delta = last - first;
  const dir = delta > 0.01 ? "up" : delta < -0.01 ? "down" : "flat";
  const word = dir === "up" ? "climbed" : dir === "down" ? "dipped" : "held steady";
  $("growth-summary").textContent =
    `Across ${history.n_sessions} quizzes, your goal readiness has ${word} `
    + `(${pct(first)} → ${pct(last)}).`;

  const track = $("growth-track");
  track.innerHTML = "";
  history.readiness_trend.forEach((r, i) => {
    const isLast = i === history.readiness_trend.length - 1;
    const bar = document.createElement("div");
    bar.className = "growth-bar" + (isLast ? " current" : "");
    bar.style.height = Math.max(6, Math.round(r * 64)) + "px";
    // every bar gets its own percentage label, not just the most recent one
    bar.innerHTML = `<span>${pct(r)}</span>`;
    track.appendChild(bar);
  });
}

// ── results ──
function renderResults(d) {
  const a = d.analysis;
  $("score-val").textContent = pct(d.score);
  $("result-goal").textContent = `toward “${a.goal}”`;
  renderGrowth(d.history);
  renderHistoryList(d.timestamp);
  renderTextSignals(d.text_signals);

  const deg = Math.round((a.readiness || 0) * 360);
  $("ring").style.background = `conic-gradient(var(--brown) ${deg}deg, var(--line) ${deg}deg)`;
  $("readiness-val").textContent = pct(a.readiness);

  $("memo-val").textContent = a.memorization_index == null ? "n/a" : pct(a.memorization_index);
  $("ece-val").textContent = a.calibration && a.calibration.ece != null ? a.calibration.ece.toFixed(2) : "n/a";

  // plain-language interpretation tags
  setTag("readiness-tag", a.readiness == null ? null
    : a.readiness >= 0.7 ? ["on track", "good"] : a.readiness >= 0.4 ? ["getting there", "mid"] : ["early days", "low"]);
  setTag("memo-tag", a.memorization_index == null ? ["need reworded pairs", "mid"]
    : a.memorization_index > 0.25 ? ["mostly memorizing", "low"] : a.memorization_index > 0.1 ? ["some memorizing", "mid"] : ["transfers well", "good"]);
  const ece = a.calibration && a.calibration.ece;
  setTag("ece-tag", ece == null ? ["no confidence data", "mid"]
    : ece > 0.2 ? ["mis-calibrated", "low"] : ece > 0.1 ? ["slightly off", "mid"] : ["well calibrated", "good"]);

  const bars = $("timing-bars"); bars.innerHTML = "";
  const tp = a.timing_profile || {};
  Object.entries(TIMING_META).forEach(([key, meta]) => {
    const v = tp[key] || 0;
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `<span class="lbl">${meta.label}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${Math.round(v*100)}%;background:${meta.color}"></span></span>
      <span>${Math.round(v*100)}%</span>`;
    bars.appendChild(row);
  });

  const gl = $("gap-list"); gl.innerHTML = "";
  if (!(a.gaps || []).length) {
    gl.innerHTML = `<p class="muted">No gaps against this goal - every required concept is at
      or above its target. Consider a harder goal or more questions.</p>`;
  }
  const maxGap = Math.max(0.001, ...(a.gaps || []).map((g) => g.gap));
  (a.gaps || []).slice(0, 5).forEach((g) => {
    const row = document.createElement("div");
    row.className = "gap-row";
    row.innerHTML = `<div class="gap-head">
        <span class="concept">${g.concept.replace(/_/g, " ")}</span>
        <span class="muted">mastery ${pct(g.mastery)} · needs ${pct(g.target)}</span>
      </div>
      <div class="gap-track"><span class="gap-fill" style="width:${Math.round((g.gap/maxGap)*100)}%"></span></div>`;
    gl.appendChild(row);
  });

  const rl = $("reflection-list"); rl.innerHTML = "";
  (a.reflection || []).forEach((line) => {
    const li = document.createElement("li"); li.textContent = line; rl.appendChild(li);
  });

  const rev = $("review-list"); rev.innerHTML = "";
  (d.graded || []).forEach((g) => {
    // stem comes embedded on stored history entries (see saveReflectionToHistory);
    // for a just-completed live quiz it's looked up from the in-memory question list
    const stem = g.stem || state.questions.find((x) => x.id === g.question_id)?.stem || g.question_id;
    const ok = g.correct === 1;
    const div = document.createElement("div");
    div.className = "review-item";
    div.innerHTML =
      `<div class="r-stem"><span class="r-mark ${ok ? "ok" : "no"}">${ok ? "✓" : "✗"}</span>${stem}</div>` +
      (ok ? "" : `<div class="muted">Correct answer: <b>${g.correct_letter}</b> · you chose ${g.chosen_letter || "none"}</div>`) +
      `<div class="r-exp">${g.explanation}</div>`;
    rev.appendChild(div);
  });
}

// segmented question-count control -> hidden #nq value
document.querySelectorAll("#nq-seg .seg-opt").forEach((el) => {
  el.addEventListener("click", () => {
    document.querySelectorAll("#nq-seg .seg-opt").forEach((o) => o.classList.remove("active"));
    el.classList.add("active");
    $("nq").value = el.dataset.n;
  });
});

// sidebar navigation (data-view items; plain-href items navigate normally)
let hasReflection = false;
document.querySelectorAll(".nav-item[data-view]").forEach((el) => {
  el.addEventListener("click", () => {
    const v = el.dataset.view;
    if (v === "results") {
      if (hasReflection) { show("results"); return; }
      // no quiz taken yet this page-load - fall back to the most recent stored
      // reflection from this browser, if any, instead of always redirecting to setup
      const hist = getReflectionHistory();
      if (hist.length) {
        renderResults(hist[0]);
        hasReflection = true;
        show("results");
      } else {
        show("start");
      }
      return;
    }
    if (v === "reports") { show("reports"); loadReports(); return; }
    if (v === "lab") { show("lab"); loadModelLab(); return; }
    if (v === "vitals") {
      // show the latest live vitals if a quiz has been taken this page-load
      if (state.lastVitals) renderVitals(state.lastVitals);
      show("vitals");
      return;
    }
    show(v);
  });
});
$("welcome-cta").addEventListener("click", enterApp);
// "See how it works" enters the app and opens the live architecture diagram
$("see-how-btn").addEventListener("click", () => { enterApp(); show("architecture"); });
$("brand-home").addEventListener("click", showLanding);

// inject the two reactive faces once (compact strip + full vitals screen), then reset
$("qz-face").innerHTML = faceMarkup("qz");
$("vt-face").innerHTML = faceMarkup("vt");
resetVitals();

// ── reports / monitoring ──
async function loadReports() {
  try {
    const d = await (await fetch(`${API}/api/reports`)).json();
    // status banner
    const tone = d.overall_status === "healthy" ? "good"
               : d.overall_status === "watch" ? "mid" : "low";
    $("rep-status").textContent = d.overall_status;
    $("rep-status-dot").className = "dot dot-" + tone;
    $("rep-generated").textContent = "generated " + new Date(d.generated_at).toLocaleString()
      + " · v" + d.service_version;
    const live = d.live || {};
    $("rep-sessions").textContent = live.total_sessions ?? "–";
    $("rep-answers").textContent = live.total_answers ?? "–";
    $("rep-avg-score").textContent = live.avg_score == null ? "–" : pct(live.avg_score);
    $("rep-avg-ready").textContent = live.avg_readiness == null ? "–" : pct(live.avg_readiness);

    // artifacts table
    const tb = document.querySelector("#rep-artifacts tbody");
    tb.innerHTML = "";
    (d.artifacts || []).forEach((a) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td><b>${a.artifact}</b></td><td>${a.trained_at}</td>
        <td>${a.age_days}d</td><td>${a.size_kb} KB</td>
        <td><span class="pill pill-${a.status}">${a.status}</span></td>`;
      tb.appendChild(tr);
    });

    // drift verdict
    const drift = live.drift;
    $("rep-drift").innerHTML = drift
      ? `Live drift check: older avg score <b>${pct(drift.older_avg_score)}</b> → recent
         <b>${pct(drift.recent_avg_score)}</b> (Δ ${drift.delta >= 0 ? "+" : ""}${Math.round(drift.delta*100)}pp)
         - <span class="pill pill-${drift.verdict === "stable" || drift.verdict === "improving" ? "fresh" : "stale"}">${drift.verdict}</span>`
      : `<span class="muted">Live drift check needs at least 6 stored sessions.</span>`;

    // training metrics from MLflow
    const box = $("rep-metrics");
    box.innerHTML = "";
    (d.training_metrics || []).forEach((run) => {
      const div = document.createElement("div");
      div.className = "metric-run";
      const chips = Object.entries(run.metrics)
        .map(([k, v]) => `<span class="metric-chip">${k.replace(/_/g, " ")} <b>${v}</b></span>`)
        .join("");
      div.innerHTML = `<h4>${run.run}</h4><div class="metric-chips">${chips}</div>`;
      box.appendChild(div);
    });
    if (!(d.training_metrics || []).length)
      box.innerHTML = `<span class="muted">No MLflow runs found - run scripts/run_pipeline.py to train.</span>`;
  } catch (e) {
    $("rep-status").textContent = "unreachable";
    $("rep-status-dot").className = "dot dot-low";
  }
}

// ── model lab: surface the offline research track (reads the same /api/reports payload) ──
const AUC_MODELS = [
  { key: "irt_val_auc", label: "Offline IRT", color: "#cf7b52" },
  { key: "bkt_val_auc", label: "BKT", color: "#e2a25c" },
  { key: "sakt_val_auc", label: "SAKT", color: "#8faa78" },
];

async function loadModelLab() {
  try {
    const d = await (await fetch(`${API}/api/reports`)).json();
    const runs = d.training_metrics || [];
    // flatten all runs' metrics into one lookup (keys are unique across runs)
    const metrics = {};
    runs.forEach((r) => Object.assign(metrics, r.metrics || {}));

    const rows = metrics.data_n_rows;
    $("lab-rows").textContent = rows == null ? "–" : Math.round(rows).toLocaleString();
    $("lab-skills").textContent = metrics.data_n_skills == null ? "–" : Math.round(metrics.data_n_skills);
    $("lab-estimator").textContent = (d.registry && d.registry.live_mastery_estimator) || "online IRT";

    const tone = d.overall_status === "healthy" ? "good"
               : d.overall_status === "watch" ? "mid"
               : d.overall_status === "no models" ? "mid" : "low";
    $("lab-status-dot").className = "dot dot-" + tone;
    $("lab-status-txt").textContent = d.overall_status || "unknown";

    // AUC comparison - scaled from 0.5 (chance floor) to 1.0 so real gaps are legible
    const box = $("lab-auc"); box.innerHTML = "";
    let any = false;
    AUC_MODELS.forEach((m) => {
      const auc = metrics[m.key];
      if (auc == null) return;
      any = true;
      const w = Math.max(0, Math.min(1, (auc - 0.5) / 0.5)) * 100;
      const row = document.createElement("div");
      row.className = "bar-row";
      row.innerHTML = `<span class="bar-label">${m.label}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${w}%;background:${m.color}"></span></span>
        <b style="margin-left:8px;color:var(--brown-deep)">${auc.toFixed(3)}</b>`;
      box.appendChild(row);
    });
    $("lab-auc-note").textContent = any
      ? "Bars scaled from 0.5 (chance) to 1.0. Offline IRT sits near chance on unseen learners"
        + " - the founding insight that motivated the per-session online IRT now serving live"
        + " quizzes. Sequence models (SAKT) recover the signal but need a product-scale exercise"
        + " vocabulary before they can serve live."
      : "No training runs are shipped with this deployment, so there are no offline AUCs to show.";

    // artifacts table
    const tb = document.querySelector("#lab-artifacts tbody");
    tb.innerHTML = "";
    (d.artifacts || []).forEach((a) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td><b>${a.artifact}</b></td><td>${a.trained_at}</td>
        <td>${a.age_days}d</td><td>${a.size_kb} KB</td>
        <td><span class="pill pill-${a.status === "fresh" ? "fresh" : a.status === "aging" ? "aging" : "stale"}">${a.status}</span></td>`;
      tb.appendChild(tr);
    });
    if (!(d.artifacts || []).length)
      tb.innerHTML = `<tr><td colspan="5" class="muted">No artifacts shipped with this deployment.</td></tr>`;

    // training runs: metric + param chips
    const rbox = $("lab-runs"); rbox.innerHTML = "";
    runs.forEach((run) => {
      const div = document.createElement("div");
      div.className = "metric-run";
      const chip = (k, v) => `<span class="metric-chip">${k.replace(/_/g, " ")} <b>${v}</b></span>`;
      const mchips = Object.entries(run.metrics || {}).map(([k, v]) => chip(k, v)).join("");
      const pchips = Object.entries(run.params || {}).map(([k, v]) => chip(k, v)).join("");
      div.innerHTML = `<h4>${run.run}</h4><div class="metric-chips">${mchips}${pchips}</div>`;
      rbox.appendChild(div);
    });
    if (!runs.length)
      rbox.innerHTML = `<span class="muted">No MLflow runs found - train with scripts/run_pipeline.py, or ship mlflow.db with the deploy.</span>`;
  } catch (e) {
    $("lab-status-txt").textContent = "unreachable";
    $("lab-status-dot").className = "dot dot-low";
  }
}

$("consent").addEventListener("change", (e) => { $("start-btn").disabled = !e.target.checked; });
$("start-btn").addEventListener("click", startQuiz);
$("next-btn").addEventListener("click", recordAndNext);
$("confidence").addEventListener("input", (e) => { $("conf-val").textContent = e.target.value + "%"; });
$("restart-btn").addEventListener("click", () => show("start"));

// right-to-erasure: delete this session's stored responses AND forget this device's
// growth-tracking id, so nothing links future quizzes back to what's being deleted now
$("delete-btn").addEventListener("click", async () => {
  if (!state.sessionId) return;
  if (!confirm("Delete your anonymous responses for this session and forget this device (including your saved reflection history)?")) return;
  try {
    const res = await fetch(`${API}/api/session/${state.sessionId}`, { method: "DELETE" });
    clearLearnerId();
    localStorage.removeItem(HISTORY_KEY);
    renderHistoryList();
    alert(res.ok ? "Your responses were deleted." : "Nothing to delete (already removed).");
  } catch (e) { alert("Delete failed.\n\n" + e); }
});

// Reachability check + goal hint, both from one /api/ready call. If the request fails,
// this page is very likely being served by something other than the FastAPI backend
// (a separate dev server, or opened as a raw file) - surface a visible, actionable
// banner instead of leaving it as a silent console 404/405 (see the API const comment
// above for why same-origin is always correct for this app).
(async function initReadyCheck() {
  const banner = $("origin-banner");
  const hint = $("goal-hint");
  try {
    const r = await fetch(`${API}/api/ready`);
    if (!r.ok) throw new Error();
    const d = await r.json();
    if (hint) {
      const curated = (d.curated_goals || []).map((g) => `“${g}”`).join(", ");
      hint.textContent = d.open_topics_enabled
        ? `Any topic works - built-in: ${curated || "none"}. Anything else is generated on the fly.`
        : `Open-topic generation is off on this server - built-in goals only for now: ${curated || "data science interview"}.`;
    }
  } catch {
    if (hint) hint.textContent = "";
    if (banner) {
      $("origin-here").textContent = location.origin || location.href;
      banner.classList.remove("hidden");
    }
  }
})();
