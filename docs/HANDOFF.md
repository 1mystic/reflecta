# Session handoff prompt

Paste the block below verbatim as your first message in a new Claude Code session (in this
same `g:\Dl-gen-AI` directory) to restore full working context without re-deriving it from
scratch. Update the "Known state" section before pasting if things have moved on since this
was last edited.

---

```
You're picking up work on Reflecta, a reflective learning intelligence layer over quizzes
(intent -> gap mapping is the hero feature). Read these three files in full before doing
anything else — they ARE the project memory, more reliable than anything I summarize here:

1. docs/STORY.md       — the narrative: why this exists (grew out of a Kaggle MCQ solver
                          that plateaued at 0.752 because ~25% of its answer keys were
                          wrong; the pivot was pointing the same "detect understanding vs
                          pattern-matching" primitive at learners instead of answer keys)
2. docs/GUIDEBOOK.md    — the full reference: architecture, every formula, every design
                          decision (§10 has an ADR-style log of real bugs found and fixed
                          with reasoning), and §15 is a start-to-finish worked-example
                          walkthrough of the whole request lifecycle
3. README.md            — the outward-facing summary + quickstart + results table

Known state (verify against `git log` and `pytest -q` — this can go stale):
- Backend: FastAPI (api/main.py) + an importable `reflecta` package (src/reflecta/).
- Frontend: static HTML/CSS/JS SPA, no build step, served BY the same FastAPI process
  (frontend/). A true landing page (frontend/index.html #landing, no sidebar) sits in
  front of an app shell (#app-shell, sidebar + screens) entered via "Get started".
- Question delivery: a curated bank (data/question_bank.json) for "data science
  interview", or a Claude-Haiku-generated + independently-verified bank per novel topic
  (src/reflecta/generation.py), cached to data/generated_banks/.
- Quiz sessions are DISK-BACKED (src/reflecta/sessions.py PendingSessionStore), not an
  in-memory dict — that was a real bug (uvicorn --reload wipes memory; gunicorn workers
  don't share memory), fixed and regression-tested.
- Live mastery estimation is ONLINE IRT (src/reflecta/models/online_irt.py) — a live
  per-session MAP fit, not a pretrained model file. Offline-trained IRT/BKT/SAKT models
  (525k real ASSISTments rows, tracked in local MLflow) exist as a research track but do
  NOT serve live traffic yet (see GUIDEBOOK §7.5/§15.3 for exactly why, and the seam
  where that would plug in: serving.get_mastery_estimator()).
- Docs live in docs/ (moved out of root to cut clutter); only README.md and LICENSE stay
  at repo root by GitHub convention. pyproject.toml + uv.lock are the dependency source
  of truth (no requirements.txt).
- Tests: pytest, run with `.venv/Scripts/python.exe -m pytest -q` (Windows/uv venv).
  Includes frontend markup regression tests (tests/test_frontend_markup.py) for
  DOM/CSS-semantics bugs that backend tests can't see (e.g. a <select> option
  mismatch, a <span> with display:inline silently ignoring a JS-set width:%).
- Deployment: render.yaml exists (Render free tier, Docker runtime, persistent disk
  mounted at /app/data/sessions). Not yet actually deployed as of this handoff.

House rules learned the hard way this session (read GUIDEBOOK §10 for the full list):
- No em dashes in anything user-visible (frontend pages + API error strings the
  frontend displays via alert()) — plain hyphens instead. Backend docstrings/comments
  are fine either way (not user-visible).
- Before believing a calculation is correct, actually trace it with real inputs — two
  genuine bugs (an ECE calibration boundary bug, a CSS specificity bug silently
  stretching a button full-width) were found this way, not by inspection alone.
- Every fix in this project gets a regression test, not just a patch — that's the
  established pattern, keep following it.
- Always verify a fix over a REAL running server (uvicorn on :8000) with a real HTTP
  request, not just unit tests in isolation, before calling something done.

Now: [state the actual task here].
```
