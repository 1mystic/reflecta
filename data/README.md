# Data catalog

All datasets below are **free**. Downloads land in `data/raw/` (gitignored); cleaned/feature
outputs go to `data/processed/`. Use `scripts/download_data.py` where a loader exists.

## Learner-behavior datasets (knowledge tracing — the core signal source)

| Dataset | Size | What's special | Source |
|---------|------|----------------|--------|
| **ASSISTments 2009/2012/2017** | ~½M–4M interactions | Classic KT benchmark; skills + correctness + hints. Smallest → start here. | [assistments.org](https://sites.google.com/site/assistmentsdata/home) |
| **Eedi — NeurIPS 2020 Education Challenge** | ~15M answers | Diagnostic MCQs; **distractors labeled with misconceptions**. Fuels signal #2. | [eedi.com / NeurIPS2020 comp](https://eedi.com/projects/neurips-education-challenge) |
| **Eedi — Mining Misconceptions (Kaggle 2024)** | ~1.8k questions | Each wrong option mapped to a named misconception. | Kaggle competition |
| **EdNet (Riiid)** | 131M interactions | Largest public KT log; **response timestamps** → timing signal. | [github.com/riiid/ednet](https://github.com/riiid/ednet) |
| **Junyi Academy** | ~16M | Math practice with a knowledge-structure graph. | Kaggle / PSLC DataShop |

## Question-content datasets (the items themselves)

| Dataset | Notes |
|---------|-------|
| **MMLU** + **MMLU-Redux / MMLU-Pro** | 57 subjects; Redux has *human-corrected* labels — ground truth for the "is this key wrong?" primitive. |
| **AI2 ARC** (Easy/Challenge), **OpenBookQA**, **SciQ** | Clean science MCQs with gold answers. |
| **MedMCQA** | 194k Indian NEET/AIIMS medical MCQs — large, exam-relevant. |

All content datasets load via HuggingFace `datasets`, e.g. `load_dataset("cais/mmlu", "all")`.

## Legacy

`data/legacy_kaggle/` holds the original Smart MCQ Solver competition CSVs
(`train.csv`, `test.csv`, `sample_submission.csv`, `submission_v11_loo_rank23 (1).csv`).
Kept for provenance and for the memorization-vs-understanding paraphrase probes (signal #1).

## Start small

For M1, download **ASSISTments 2009** (a single ~15MB CSV) — enough to build behavior
features, an IRT baseline, and a BKT knowledge tracer before scaling to Eedi/EdNet.
