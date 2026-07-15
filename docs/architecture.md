# Architecture

```
                    ┌─────────────────────────────────────────────┐
   quiz app  ──────▶│  interactions (learner_id, item, correct,    │
   (or public       │  response_time, chosen_option, confidence,   │
    KT dataset)     │  paraphrase_group, is_reworded)              │
                    └───────────────────┬─────────────────────────┘
                                        │  canonical long-format schema
                    ┌───────────────────▼─────────────────────────┐
                    │  reflecta.features.behavior                  │
                    │  timing profile · memorization index ·       │
                    │  distractor signature · confidence pairs     │
                    └──────┬───────────────────────┬───────────────┘
             mastery       │                       │  confidence, correct
        ┌─────────────────▼──────┐        ┌────────▼──────────────┐
        │ models.irt (ability θ) │        │ eval.metrics          │
        │ models.knowledge_tracing│       │ ECE · Brier · AUC     │
        │ (BKT → SAKT)           │        └───────────────────────┘
        └────────┬───────────────┘
     mastery vec │
        ┌────────▼───────────────────────────────┐
        │ models.intent_gap  (HERO)               │
        │ goal → requirement vector →             │
        │ mastery projection → gap + misallocation│
        └────────┬────────────────────────────────┘
                 │  GapReport + signal bundle
        ┌────────▼────────────────┐      ┌──────────────────────┐
        │ reflection.engine        │◀────│ tracking.experiment  │
        │ rules-first (+ free LLM) │     │ W&B / MLflow / none   │
        └────────┬────────────────┘      └──────────────────────┘
                 │  reflection lines + structured report
        ┌────────▼────────────────────────────────────────────┐
        │ api.main  /api/analyze   ──▶  frontend/ (SaaS UI)    │
        └──────────────────────────────────────────────────────┘
```

## Design principles

- **Self-contained.** Everything (venv, data, models) lives under this directory. No system
  changes, no external services required to run the core demo.
- **Graceful degradation.** Missing signals (e.g. no confidence in public logs) become NaN and
  are simply omitted, never crash. Tracking falls back to console when no W&B key. Reflection
  falls back to rules when no LLM.
- **Explanation is the product.** intent→gap is transparent arithmetic over named concepts, so
  every reflection line traces back to a computed number — no black box between signal and advice.
- **Free-only.** Open/local models, free dataset hosting, free-tier tracking.

## Layout → responsibility

| Path | Responsibility |
|------|----------------|
| `src/reflecta/data/` | synthetic bootstrap + loaders that normalize public datasets |
| `src/reflecta/features/` | behavior-signal extraction |
| `src/reflecta/models/` | IRT, knowledge tracing, intent→gap |
| `src/reflecta/eval/` | calibration + KT metrics |
| `src/reflecta/reflection/` | reflection-prompt engine |
| `src/reflecta/tracking/` | W&B/MLflow/none wrapper |
| `api/` | FastAPI backend + static hosting |
| `frontend/` | clean SaaS UI (static, no build step) |
| `notebooks/` | research: EDA, KT training, ablations |
```
