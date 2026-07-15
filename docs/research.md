# Research spine

Reflecta's claims are grounded in published work and public datasets. Sources below were
verified on the web (July 2026).

## The premise: quiz "answers" and "scores" hide the real signal

- **Label noise is real and measurable.** *Are We Done with MMLU?* (Gema et al., 2024)
  re-annotated MMLU and built **MMLU-Redux** (~5,700 questions, 57 subjects) with an explicit
  error taxonomy — *Wrong Ground Truth, No Correct Answer, Multiple Correct Answers, Bad
  Question/Options Clarity*. They estimate **6.49% of MMLU questions contain errors, rising to
  ~57% in some subjects (Virology)**, and show model rankings change after correction.
  → This validates the legacy Smart MCQ Solver's core finding that a large fraction of answer
  keys are wrong/ambiguous, and motivates *understanding-based* signals over key-matching.
  arXiv:2406.04127 · https://github.com/aryopg/mmlu-redux

- **Distractors encode misconceptions by design.** The **Eedi / NeurIPS 2020 Education
  Challenge** dataset is **20M answers, 125k students, 28k math MCQs**, where "distractors
  embody misconceptions," and the challenge itself included an **automatic question-quality
  assessment** task. → Direct fuel for signal #2 (misconception diagnosis) and the
  content-QA angle. arXiv:2007.12061 · arXiv:2104.04034

## The five signals → their literature

| Signal | Method | Anchor |
|--------|--------|--------|
| #1 Memorization vs understanding | transfer/paraphrase-invariance probe | descends from the legacy paraphrase analysis; consistent with generalization-vs-memorization work |
| #2 Misconception diagnosis | distractor → misconception mapping | Eedi NeurIPS 2020; Eedi Kaggle 2024 "Mining Misconceptions in Mathematics" |
| #3a Mastery (static) | **Item Response Theory** (1PL/Rasch → 2PL) | separates learner ability θ from item difficulty b |
| #3b Mastery (temporal) | **Knowledge Tracing**: BKT (2-state HMM) → **DKT** (RNN) → **SAKT** (self-attention) | metric = next-question AUC |
| #3c Confidence | **ECE** + **Brier score** | detects Dunning–Kruger (high confidence, low accuracy) |
| #4 Intent → gap (HERO) | goal decomposition → requirement vector → mastery projection → residual gap | novel synthesis; transparent arithmetic over named concepts |
| #5 Reflection | rules-first templates, optional free/local LLM rephrasing | LLM never invents facts — only rephrases computed signals |

## Why IRT/KT and not raw % correct

Raw accuracy conflates *how hard the items were* with *how able the learner is*. IRT/KT
separate them, so "mastery" is comparable across learners who saw different questions — a
prerequisite for honest intent→gap mapping.

## Evaluation discipline (inherited lesson)

The legacy project's most painful lesson: random 80/20 splits **leak** when the data has
duplicated/near-duplicate items (val 0.92 vs LB 0.73). Reflecta uses **group-aware splits**
(by learner and by concept) for every reported number. See `docs/legacy/` for the full
post-mortem.

## Datasets (all free) — see `data/README.md`

Learner behavior: ASSISTments, Eedi, EdNet (131M interactions with timestamps), Junyi.
Question content: MMLU / MMLU-Redux, ARC, OpenBookQA, SciQ, MedMCQA (194k Indian medical MCQs).

## Sources

- [Are We Done with MMLU? (arXiv:2406.04127)](https://arxiv.org/abs/2406.04127) · [MMLU-Redux repo](https://github.com/aryopg/mmlu-redux)
- [Diagnostic Questions: NeurIPS 2020 Education Challenge (arXiv:2007.12061)](https://arxiv.org/abs/2007.12061)
- [Results & Insights: NeurIPS 2020 Education Challenge (arXiv:2104.04034)](https://arxiv.org/abs/2104.04034)
