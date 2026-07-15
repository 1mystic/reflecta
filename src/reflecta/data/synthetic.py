"""Synthetic learner logs — so the pipeline, demo, and tests run with no downloads.

Generates interactions from an IRT-style process with injected metacognitive quirks:
  - per-learner ability and per-skill difficulty (drives correctness)
  - a "memorizer" persona whose accuracy collapses on reworded items
  - response times correlated with (ability - difficulty)
  - confidence that is deliberately mis-calibrated for some learners

This is bootstrap/validation data — NOT a substitute for the public KT datasets, but it
lets every component be exercised end-to-end today.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SKILLS = ["probability", "linear_algebra", "sql", "ml_fundamentals", "trivia_history"]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + np.exp(-x))


def generate_learner_log(
    learner_id: int = 0,
    n_items: int = 60,
    ability: float | None = None,
    memorizer: bool = False,
    overconfident: bool = False,
    seed: int | None = None,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed if seed is not None else learner_id)
    ability = rng.normal(0.3, 0.8) if ability is None else ability

    rows = []
    for i in range(n_items):
        skill = rng.choice(SKILLS)
        difficulty = {"probability": 0.4, "linear_algebra": 0.6, "sql": 0.1,
                      "ml_fundamentals": 0.5, "trivia_history": -0.2}[skill]
        is_reworded = int(rng.random() < 0.35)
        logit = ability - difficulty
        if memorizer and is_reworded:
            logit -= 1.6  # transfer failure: reworded items much harder for memorizers
        p_correct = _sigmoid(logit)
        correct = int(rng.random() < p_correct)

        # response time: faster when |logit| large (fluent or hopeless); slower near the margin
        base_rt = 8 + 20 * np.exp(-abs(logit)) + rng.normal(0, 2)
        response_time = max(1.5, base_rt)

        # chosen option: correct label 'C' if correct, else a peaked distractor (misconception)
        if correct:
            chosen = "C"
        else:
            chosen = rng.choice(["A", "B", "D", "E"], p=[0.5, 0.2, 0.2, 0.1])

        # confidence: overconfident learners report high confidence regardless of correctness
        if overconfident:
            confidence = float(np.clip(rng.normal(0.85, 0.08), 0, 1))
        else:
            confidence = float(np.clip(_sigmoid(logit) + rng.normal(0, 0.12), 0, 1))

        rows.append(dict(
            learner_id=learner_id, item_id=i, skill=skill, correct=correct,
            response_time=round(response_time, 2), chosen_option=chosen,
            confidence=round(confidence, 3), paraphrase_group=f"{skill}_{i % 12}",
            is_reworded=is_reworded,
        ))
    return pd.DataFrame(rows)


def generate_cohort(n_learners: int = 40, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    for lid in range(n_learners):
        frames.append(generate_learner_log(
            learner_id=lid,
            memorizer=bool(rng.random() < 0.3),
            overconfident=bool(rng.random() < 0.3),
            seed=seed + lid,
        ))
    return pd.concat(frames, ignore_index=True)
