"""Reflecta FastAPI backend — production-hardened.

    uvicorn api.main:app --reload          # dev, http://localhost:8000  (docs at /docs)
    gunicorn -k uvicorn.workers.UvicornWorker api.main:app   # prod (see Dockerfile)

Endpoints
  GET    /api/health         liveness
  GET    /api/ready          readiness (bank + models loaded)
  GET    /api/model/info     deployed model artifacts + live estimator
  POST   /api/analyze        persona-demo analysis
  POST   /api/quiz/start     begin a live quiz (answers hidden; consent-gated)
  POST   /api/quiz/submit    grade + analyze + persist (anonymous)
  DELETE /api/session/{id}   right-to-erasure (delete a stored session)
"""
from __future__ import annotations

import math
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from reflecta.config import CONFIG
from reflecta.data.question_bank import QuestionBank
from reflecta.data.synthetic import generate_learner_log
from reflecta.eval.metrics import brier_score, expected_calibration_error
from reflecta.features.behavior import (
    confidence_pairs,
    extract_behavior_signals,
    per_skill_mastery,
)
from reflecta.logging_config import get_logger
from reflecta.models.intent_gap import IntentGapMapper
from reflecta.reflection.engine import generate_reflection
from reflecta.serving import get_mastery_estimator, model_registry_info
from reflecta.sessions import FileSessionStore

from api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    GapItemOut,
    GradedItem,
    LearnerHistoryOut,
    QuizStartRequest,
    QuizStartResponse,
    QuizSubmitRequest,
    QuizSubmitResponse,
    ServedQuestionOut,
)

log = get_logger("reflecta.api")
app = FastAPI(title="Reflecta API", version=CONFIG.version,
              description="A reflective learning intelligence layer.")

# CORS: explicit origins in prod (never "*" with credentials in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(CONFIG.cors_origins) if CONFIG.is_prod else ["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

_mapper = IntentGapMapper()
_bank = QuestionBank()
_store = FileSessionStore()
_mastery = get_mastery_estimator()
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"

# session answer keys held server-side so answers never reach the client
_SESSION_KEYS: dict[str, dict] = {}
_SESSION_GOAL: dict[str, str] = {}
# goal-specific concept requirements for sessions on generated topic banks
_SESSION_REQS: dict[str, list] = {}
# opaque client-generated learner id for this session, if the client sent one
_SESSION_LEARNER: dict[str, str] = {}

# lightweight in-memory per-IP rate limiter (swap for Redis in multi-worker prod)
_HITS: dict[str, deque] = defaultdict(deque)


def _clean(x) -> float | None:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return float(x)


# ---------- middleware: request id, access log, rate limit ----------
@app.middleware("http")
async def observability(request: Request, call_next):
    rid = uuid.uuid4().hex[:8]
    start = time.time()

    # rate limit only mutating quiz endpoints
    if request.url.path.startswith("/api/quiz"):
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        hits = _HITS[ip]
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= CONFIG.rate_limit_per_min:
            return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})
        hits.append(now)

    try:
        response = await call_next(request)
    except Exception:  # never leak stack traces to clients
        log.exception("unhandled_error", extra={"rid": rid, "path": request.url.path})
        return JSONResponse(status_code=500, content={"detail": "internal error", "rid": rid})

    response.headers["X-Request-ID"] = rid
    log.info("request", extra={"rid": rid, "method": request.method,
                               "path": request.url.path, "status": response.status_code,
                               "ms": round((time.time() - start) * 1000, 1)})
    return response


# ---------- quiz delivery: curated bank, or Claude-generated for novel topics ----------
def _goal_is_curated(goal: str) -> bool:
    """True only when the goal's resolved concepts actually exist in the curated question
    bank's content — not just in the resolver's static library.

    A goal can be *listed* in IntentGapMapper's curated library (a set of concept
    requirements) without any matching *questions* existing in data/question_bank.json —
    e.g. "neet biology" has requirements defined but the bank only contains data-science
    questions. Trusting the resolver alone would silently serve mismatched questions
    (data-science items) scored against unrelated gap requirements (biology concepts),
    producing a nonsensical reflection. Require actual overlap with the bank's content.
    """
    reqs = IntentGapMapper._default_resolver(goal)
    if len(reqs) == 1 and reqs[0].concept == "general":
        return False
    bank_concepts = _bank.concepts()
    return any(r.concept in bank_concepts for r in reqs)


def _delivery_for_goal(goal: str, n: int):
    """Return (delivery, requirements|None). Novel topics use a Claude-generated bank
    (cached per topic); requirements come back with it for intent->gap."""
    from reflecta import generation
    from reflecta.models.intent_gap import ConceptRequirement

    if _goal_is_curated(goal):
        return _bank.sample(n=n), None

    try:
        bank = generation.generate_bank(goal, n_questions=max(n, 10))
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail=("This topic isn't in the built-in bank, and open-topic generation is "
                    "disabled. Set ANTHROPIC_API_KEY on the server to enable quizzes on "
                    "any topic, or try the built-in goal 'data science interview'."))
    except Exception:
        log.exception("bank_generation_failed", extra={"goal": goal})
        raise HTTPException(status_code=503,
                            detail="Topic generation is temporarily unavailable, "
                                   "please try again in a minute.")

    reqs = [ConceptRequirement(c["concept"], c["importance"], c["target"])
            for c in bank.get("concepts", [])] or None
    return QuestionBank.from_dict(bank).sample(n=n), reqs


# ---------- shared analysis pipeline ----------
def _analyze(goal: str, df: pd.DataFrame, requirements: list | None = None) -> AnalyzeResponse:
    signals = extract_behavior_signals(df)
    conf, corr = confidence_pairs(df)
    calibration = {
        "ece": _clean(expected_calibration_error(conf, corr)) if len(conf) else None,
        "brier": _clean(brier_score(conf, corr)) if len(conf) else None,
        "n": int(len(conf)),
    }
    if len(conf):
        # direction > 0 = overconfident, < 0 = underconfident; drives the reflection line
        calibration["direction"] = _clean(float(conf.mean() - corr.mean()))
    signals["calibration"] = calibration
    if "difficulty" in df.columns and df["difficulty"].notna().any():
        mastery = _mastery.estimate(df)          # difficulty-aware online IRT
    else:
        mastery = per_skill_mastery(df)          # raw accuracy fallback (persona demo)
    effort = df["skill"].value_counts(normalize=True).to_dict() if "skill" in df else {}
    gap = _mapper.analyze(goal, mastery, effort, requirements=requirements)
    return AnalyzeResponse(
        goal=gap.goal, readiness=gap.readiness,
        overall_accuracy=_clean(signals["overall_accuracy"]) or 0.0,
        memorization_index=_clean(signals["memorization_index"]),
        timing_profile=signals["timing_profile"], calibration=calibration,
        # only real gaps — a concept already at/above its target is not a "gap"
        gaps=[GapItemOut(**g.__dict__) for g in gap.top_gaps if g.gap > 0][:5],
        misallocation=gap.misallocation, reflection=generate_reflection(signals, gap),
    )


def _learner_history(learner_id: str) -> LearnerHistoryOut | None:
    """Readiness/score trend across this opaque learner's past sessions — the payoff of
    persisting `learner_id`: mastery signal that accumulates instead of resetting cold
    every quiz. Returns None if this is the learner's first stored session."""
    sessions = _store.for_learner(learner_id)
    if not sessions:
        return None
    readiness, scores = [], []
    for s in sessions:
        r = (s.get("analysis") or {}).get("readiness")
        sc = s.get("score")
        if r is not None and sc is not None:
            readiness.append(float(r))
            scores.append(float(sc))
    if not readiness:
        return None
    return LearnerHistoryOut(n_sessions=len(readiness),
                             readiness_trend=readiness, score_trend=scores)


# ---------- ops endpoints ----------
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "reflecta", "version": CONFIG.version}


@app.get("/api/ready")
def ready() -> dict:
    from reflecta import generation

    ok = len(_bank._raw) > 0
    if not ok:
        raise HTTPException(status_code=503, detail="question bank not loaded")
    # only report goals with real matching bank content (see _goal_is_curated) — the
    # resolver's library alone is not a promise that questions exist for a name
    verified_goals = [g for g in IntentGapMapper.curated_goal_names() if _goal_is_curated(g)]
    return {"status": "ready", "questions": len(_bank._raw),
            "sessions_stored": _store.count(),
            "curated_goals": sorted(verified_goals),
            "open_topics_enabled": generation.is_available()}


@app.get("/api/model/info")
def model_info() -> dict:
    return model_registry_info()


@app.get("/api/reports")
def reports() -> dict:
    """Operator/user-facing monitoring: model registry, staleness ('rot'), training
    metrics from MLflow, live session stats, and drift verdicts."""
    from reflecta.monitoring import build_report

    return build_report()


# ---------- product endpoints ----------
@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    if req.interactions:
        df = pd.DataFrame([i.model_dump() for i in req.interactions])
    else:
        persona = (req.demo_persona or "").lower()
        df = generate_learner_log(learner_id=1, n_items=80,
                                  memorizer="memoriz" in persona,
                                  overconfident="overconfid" in persona, seed=7)
    return _analyze(req.goal, df)


@app.post("/api/quiz/start", response_model=QuizStartResponse)
def quiz_start(req: QuizStartRequest) -> QuizStartResponse:
    if CONFIG.require_consent and not req.consent:
        raise HTTPException(status_code=403,
                            detail="consent required to store anonymous responses")
    delivery, requirements = _delivery_for_goal(req.goal, req.n_questions)
    session_id = uuid.uuid4().hex[:12]
    # the learner id is opaque and client-generated (localStorage); if the client has
    # none yet (first visit, or declined persistence) mint one and hand it back —
    # it is never linked to a name/email/IP, only used to group anonymous sessions
    # so mastery can be shown to accumulate over repeat quizzes.
    learner_id = req.learner_id or uuid.uuid4().hex
    _SESSION_KEYS[session_id] = delivery.key
    _SESSION_GOAL[session_id] = req.goal
    _SESSION_LEARNER[session_id] = learner_id
    if requirements:
        _SESSION_REQS[session_id] = requirements
    log.info("quiz_started", extra={"session_id": session_id, "n": len(delivery.questions),
                                    "generated": requirements is not None})
    return QuizStartResponse(
        session_id=session_id, goal=req.goal, learner_id=learner_id,
        questions=[ServedQuestionOut(**q.__dict__) for q in delivery.questions],
    )


@app.post("/api/quiz/submit", response_model=QuizSubmitResponse)
def quiz_submit(req: QuizSubmitRequest) -> QuizSubmitResponse:
    key = _SESSION_KEYS.get(req.session_id)
    if key is None:
        raise HTTPException(status_code=404, detail="unknown or expired session_id")
    goal = _SESSION_GOAL.get(req.session_id, "data science interview")

    rows, graded = [], []
    for ans in req.answers:
        entry = key.get(ans.question_id)
        if entry is None:
            continue
        row = QuestionBank.grade(ans.model_dump(), entry)
        rows.append(row)
        graded.append(GradedItem(
            question_id=ans.question_id, correct=row["correct"],
            correct_letter=row["correct_letter"], chosen_letter=ans.chosen_letter,
            explanation=row["explanation"]))
    if not rows:
        raise HTTPException(status_code=400, detail="no gradeable answers")

    df = pd.DataFrame(rows)
    analysis = _analyze(goal, df, requirements=_SESSION_REQS.get(req.session_id))
    score = float(df["correct"].mean())
    learner_id = _SESSION_LEARNER.get(req.session_id)

    _store.save(req.session_id, {
        "session_id": req.session_id,
        "learner_id": learner_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "goal": goal, "score": score, "interactions": rows,
        "analysis": analysis.model_dump(),
    })
    history = _learner_history(learner_id) if learner_id else None

    _SESSION_KEYS.pop(req.session_id, None)
    _SESSION_GOAL.pop(req.session_id, None)
    _SESSION_REQS.pop(req.session_id, None)
    _SESSION_LEARNER.pop(req.session_id, None)
    return QuizSubmitResponse(session_id=req.session_id, score=score,
                              graded=graded, analysis=analysis, history=history)


@app.delete("/api/session/{session_id}")
def delete_session(session_id: str) -> dict:
    """Right-to-erasure: delete a stored session on request."""
    removed = _store.delete(session_id)
    if not removed:
        raise HTTPException(status_code=404, detail="session not found")
    return {"deleted": session_id}


# serve the static frontend at / (mounted last so /api/* wins)
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
