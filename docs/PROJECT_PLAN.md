# Reflecta — Project Plan

## Context: why this project exists

The predecessor was a Kaggle "Smart MCQ Solver" that plateaued at **0.752 MAP@3**. Deep
error analysis (`docs/legacy/`) proved the ceiling was **label noise** — roughly a quarter of
the answer keys were wrong or ambiguous, and no similarity/feature trick could fix that.
The genuinely novel discovery underneath was: *you can separate real understanding from
surface pattern-matching by testing invariance across rephrasings.*

Pointed at answer keys, that's a dead end. Pointed at **learners**, it's a real, under-served
product: a **metacognition layer** that tells someone whether they understand, why they're
learning, and what to do next. That is Reflecta.

## Locked decisions

| Decision | Choice |
|----------|--------|
| Direction | Metacognition layer over quizzes |
| Hero feature | **Intent → gap mapping** |
| Target community | Edtech content QA / self-directed learners |
| Data | Public KT datasets (Eedi, EdNet, ASSISTments) **+** own quiz app |
| LLM budget | **Free only** (open/local models) |
| Depth | Balanced: real research core + shippable SaaS UI |
| Course grading | Out of scope — this is a personal/portfolio evolution |
| Tracking | W&B (free tier) with MLflow-compatible wrapper |

## Research spine (the "research side")

1. **Item Response Theory (IRT)** — 1PL/2PL to estimate learner ability θ and item
   difficulty/discrimination. Grounds "mastery" in a principled latent trait.
2. **Knowledge Tracing** — BKT (interpretable baseline) → DKT/SAKT (neural) to model mastery
   *over time*. Metric: next-question AUC.
3. **Confidence calibration** — Expected Calibration Error (ECE) & Brier score to detect
   over/under-confidence (Dunning–Kruger).
4. **Misconception mining** — map distractors to named misconceptions using Eedi's labeled data.
5. **Intent → gap (novel synthesis)** — decompose a stated goal into a skill/concept
   requirement vector, project the learner's mastery vector onto it, and surface the residual
   as the actionable gap.

## Milestones

- [x] **M0 — Scaffold**: repo structure, package, dataset catalog, UI shell, FastAPI, tracking.
- [x] **M1 — Data & baselines**: real ASSISTments (525k rows) ingested → cleaned → group split
      (by learner) → IRT baseline. MLflow run logged. *IRT val AUC=0.51 — near chance because
      1PL can't cold-start held-out learners; documented as an honest limitation.*
- [x] **M2 — Knowledge tracing**: BKT per-skill baseline. **Val next-question AUC = 0.763**
      (12 skills), logged to MLflow, artifacts in `models_store/`. SAKT/DKT = next.
- [x] **M3 — Intent→gap engine**: goal→requirement mapping, mastery projection, gap +
      misallocation. Live in `models/intent_gap.py` and wired through the API.
- [x] **M4 — Reflection engine (rules)**: signals → specific prompts; optional free/local LLM.
- [x] **M5 — Product (v1)**: quiz app captures live answers/confidence/timing, grades
      server-side, persists sessions, renders the five signals. Calm SaaS UI.
- [x] **M5.1 — Online ability estimation**: `models/online_irt.py` MAP-estimates a new
      learner's θ from their session with item difficulties frozen (bank-authored), so live
      mastery is difficulty-aware IRT, not raw accuracy. Wired into the API + tested.
- [x] **M5.2 — SAKT neural KT**: `models/sakt.py` self-attentive KT + `scripts/train_sakt.py`
      (MLflow-logged) + `notebooks/02_knowledge_tracing.ipynb`. Trains on real ASSISTments.
- [ ] **M6 — Writeup**: honest eval, ablations, MLflow report, short research note. Stretch:
      per-item SAKT, forgetting feature from response-time gaps, Eedi misconception join (signal #2).

## Immediate next steps (after scaffold)

1. `scripts/download_data.py` — wire real download URLs for ASSISTments (smallest) and Eedi.
2. Implement `reflecta.models.irt` 1PL and validate ability recovery on synthetic data.
3. Flesh out `reflecta.features.behavior` on real ASSISTments logs.
4. Replace the frontend mock data with a real `/api/analyze` call.

## Free infrastructure

- **Compute**: local + Kaggle/Colab notebooks (free GPU for SAKT).
- **Tracking**: Weights & Biases free tier (`WANDB_API_KEY` in `.env`).
- **Hosting (later)**: HuggingFace Spaces / Render free tier for the API; static host for UI.
