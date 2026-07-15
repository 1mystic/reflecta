// Reflecta — live quiz flow. Talks to the FastAPI backend.
const API = (location.port === "8000" || location.protocol === "file:")
  ? "http://localhost:8000" : "";
const $ = (id) => document.getElementById(id);
const pct = (x) => (x == null ? "–" : Math.round(x * 100) + "%");

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

let state = {
  sessionId: null, goal: "", questions: [], idx: 0,
  answers: {}, selected: null, questionStart: 0,
};

const PAGE_TITLE = { welcome: "Home", start: "Take Quiz", quiz: "Quiz",
                     results: "Your Reflection", reports: "Reports" };
const SCREENS = ["welcome", "start", "quiz", "results", "reports"];

function show(screen) {
  SCREENS.forEach((s) => $(`screen-${s}`).classList.toggle("hidden", s !== screen));
  document.getElementById("page-title").textContent = PAGE_TITLE[screen] || "Home";
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
        n_questions: parseInt($("nq").value, 10),
        consent: $("consent").checked,
      }),
    });
    if (!res.ok) {
      // surface the server's message (e.g. how to enable open-topic generation)
      const detail = (await res.json().catch(() => ({})))?.detail;
      throw new Error(detail || `API ${res.status}`);
    }
    const data = await res.json();
    state = { sessionId: data.session_id, goal: data.goal, questions: data.questions,
              idx: 0, answers: {}, selected: null, questionStart: 0 };
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
  $("next-btn").textContent = state.idx === n - 1 ? "Finish ✓" : "Next →";
  state.questionStart = performance.now();
}

function recordAndNext() {
  const q = state.questions[state.idx];
  const elapsed = (performance.now() - state.questionStart) / 1000;
  state.answers[q.id] = {
    question_id: q.id,
    chosen_letter: state.selected,
    response_time: Math.round(elapsed * 100) / 100,
    confidence: parseInt($("confidence").value, 10) / 100,
  };
  if (state.idx < state.questions.length - 1) {
    state.idx += 1;
    renderQuestion();
  } else {
    submitQuiz();
  }
}

async function submitQuiz() {
  const btn = $("next-btn");
  btn.disabled = true; btn.textContent = "Analyzing…";
  try {
    const res = await fetch(`${API}/api/quiz/submit`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, answers: Object.values(state.answers) }),
    });
    if (!res.ok) throw new Error(`API ${res.status}`);
    renderResults(await res.json());
    hasReflection = true;
    show("results");
  } catch (e) {
    alert("Submission failed.\n\n" + e);
    btn.disabled = false;
  }
}

// ── results ──
function renderResults(d) {
  const a = d.analysis;
  $("score-val").textContent = pct(d.score);
  $("result-goal").textContent = `toward “${a.goal}”`;

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
    gl.innerHTML = `<p class="muted">No gaps against this goal — every required concept is at
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
    const q = state.questions.find((x) => x.id === g.question_id);
    const ok = g.correct === 1;
    const div = document.createElement("div");
    div.className = "review-item";
    div.innerHTML =
      `<div class="r-stem"><span class="r-mark ${ok ? "ok" : "no"}">${ok ? "✓" : "✗"}</span>${q ? q.stem : g.question_id}</div>` +
      (ok ? "" : `<div class="muted">Correct answer: <b>${g.correct_letter}</b> · you chose ${g.chosen_letter || "—"}</div>`) +
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
    if (v === "results") { show(hasReflection ? "results" : "start"); return; }
    if (v === "reports") { show("reports"); loadReports(); return; }
    show(v);
  });
});
$("welcome-cta").addEventListener("click", () => show("start"));

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
         — <span class="pill pill-${drift.verdict === "stable" || drift.verdict === "improving" ? "fresh" : "stale"}">${drift.verdict}</span>`
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
      box.innerHTML = `<span class="muted">No MLflow runs found — run scripts/run_pipeline.py to train.</span>`;
  } catch (e) {
    $("rep-status").textContent = "unreachable";
    $("rep-status-dot").className = "dot dot-low";
  }
}

$("consent").addEventListener("change", (e) => { $("start-btn").disabled = !e.target.checked; });
$("start-btn").addEventListener("click", startQuiz);
$("next-btn").addEventListener("click", recordAndNext);
$("confidence").addEventListener("input", (e) => { $("conf-val").textContent = e.target.value + "%"; });
$("restart-btn").addEventListener("click", () => show("start"));

// right-to-erasure: delete this session's stored responses
$("delete-btn").addEventListener("click", async () => {
  if (!state.sessionId) return;
  if (!confirm("Delete your anonymous responses for this session?")) return;
  try {
    const res = await fetch(`${API}/api/session/${state.sessionId}`, { method: "DELETE" });
    alert(res.ok ? "Your responses were deleted." : "Nothing to delete (already removed).");
  } catch (e) { alert("Delete failed.\n\n" + e); }
});
