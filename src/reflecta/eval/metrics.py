"""Evaluation metrics for Reflecta.

Two families:
  - calibration metrics (ECE, Brier)  -> signal #3 "over/under-confidence"
  - knowledge-tracing metrics (AUC)   -> next-question prediction quality

All functions are dependency-light (numpy + optional sklearn) and pure.
"""
from __future__ import annotations

import numpy as np


def brier_score(probs: np.ndarray, outcomes: np.ndarray) -> float:
    """Mean squared error between predicted probability and binary outcome.

    Lower is better. A perfectly calibrated *and* confident model scores 0.
    """
    probs = np.asarray(probs, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    return float(np.mean((probs - outcomes) ** 2))


def expected_calibration_error(
    probs: np.ndarray, outcomes: np.ndarray, n_bins: int = 10
) -> float:
    """Expected Calibration Error.

    Bins predictions by confidence and measures the gap between average confidence
    and average accuracy in each bin, weighted by bin population. This is how we
    quantify Dunning-Kruger: high confidence + low accuracy => large ECE.
    """
    probs = np.asarray(probs, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(probs)
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (probs > lo) & (probs <= hi)
        if not mask.any():
            continue
        conf = probs[mask].mean()
        acc = outcomes[mask].mean()
        ece += (mask.sum() / n) * abs(conf - acc)
    return float(ece)


def next_question_auc(probs: np.ndarray, outcomes: np.ndarray) -> float:
    """ROC-AUC of predicted correctness vs actual — the standard KT metric.

    Falls back to a manual computation if scikit-learn is unavailable.
    """
    outcomes = np.asarray(outcomes, dtype=int)
    probs = np.asarray(probs, dtype=float)
    if len(np.unique(outcomes)) < 2:
        return float("nan")
    try:
        from sklearn.metrics import roc_auc_score

        return float(roc_auc_score(outcomes, probs))
    except Exception:
        # Mann-Whitney U estimator of AUC
        order = np.argsort(probs)
        ranks = np.empty_like(order, dtype=float)
        ranks[order] = np.arange(1, len(probs) + 1)
        pos = outcomes == 1
        n_pos, n_neg = pos.sum(), (~pos).sum()
        auc = (ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
        return float(auc)


def map_at_3(ground_truth: list[str], predictions: list[str]) -> float:
    """Legacy MCQ metric (kept for continuity with the Kaggle predecessor).

    predictions: list of space-joined label strings, e.g. "B C A".
    """
    scores = []
    for true, pred in zip(ground_truth, predictions):
        pred_list = pred.strip().split()[:3]
        scores.append(1.0 / (pred_list.index(true) + 1) if true in pred_list else 0.0)
    return float(np.mean(scores)) if scores else 0.0
