# Notebooks — the research track

Run these on free compute (Kaggle/Colab give free GPU for the neural KT models). Each notebook
imports the `reflecta` package, so keep the venv active or `pip install -e .` in the notebook.

| Notebook | Milestone | Output |
|----------|-----------|--------|
| `01_data_exploration.ipynb` | M1 | EDA on ASSISTments/Eedi; behavior-signal sanity; group-aware split |
| `02_knowledge_tracing.ipynb` | M2 | BKT baseline → SAKT/DKT (torch); report next-question AUC; log to W&B |
| `03_intent_gap.ipynb` | M3 | validate intent→gap on held-out learners; LLM goal-decomposition resolver |
| `04_misconception_mining.ipynb` | later | join distractor signatures with Eedi misconception labels (signal #2) |

Start by generating a figure from the synthetic pipeline:

```python
from reflecta.data.synthetic import generate_cohort
from reflecta.features.behavior import extract_behavior_signals
cohort = generate_cohort(40)
# ... explore, then swap in real ASSISTments via reflecta.data.loaders.load_assistments()
```
