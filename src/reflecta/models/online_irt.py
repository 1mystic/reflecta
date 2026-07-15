"""Online ability estimation — make IRT work for a *new* learner (cold-start).

The offline IRT (models/irt.py) learns item difficulties b_j and per-learner abilities
theta_i jointly. A brand-new learner (a live quiz taker) has no theta_i, which is exactly
why offline IRT scored ~chance on held-out learners. The fix: **freeze the item
difficulties and estimate just this learner's theta** from their handful of responses.

Given responses y_i in {0,1} to items with known difficulty b_i, we find the MAP estimate

    theta* = argmax_theta  Σ_i [ y_i(theta - b_i) - log(1+e^{theta-b_i}) ] - theta^2 / (2σ²)

by Newton's method. The Gaussian prior N(0, σ²) is essential: with only 2-4 items per
concept, an all-correct or all-wrong run would send the MLE to ±∞; the prior keeps theta
finite and shrinks sparse evidence toward the population average (theta=0).

For the live quiz, item difficulties come from the question bank's authored `difficulty`
(0..1), mapped onto the logit scale. This is the same IRT method validated offline on
ASSISTments, now applied per-session.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def bank_difficulty_to_b(difficulty: float, scale: float = 4.0) -> float:
    """Map an authored difficulty in [0,1] to an IRT difficulty b on the logit scale.

    0.5 (average) -> 0 ; 0 (trivial) -> -scale/2 ; 1 (very hard) -> +scale/2.
    """
    return (float(difficulty) - 0.5) * scale


def estimate_ability(
    correct: np.ndarray, b: np.ndarray, prior_sd: float = 1.6, iters: int = 50
) -> float:
    """MAP estimate of a single learner's ability theta given fixed item difficulties b."""
    y = np.asarray(correct, dtype=float)
    b = np.asarray(b, dtype=float)
    if len(y) == 0:
        return 0.0
    theta = 0.0
    inv_var = 1.0 / (prior_sd ** 2)
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-(theta - b)))
        grad = np.sum(y - p) - theta * inv_var
        hess = -np.sum(p * (1 - p)) - inv_var  # < 0
        step = grad / hess
        theta -= step
        theta = float(np.clip(theta, -4.0, 4.0))
        if abs(step) < 1e-6:
            break
    return theta


def ability_to_mastery(theta: float) -> float:
    """Convert ability theta to a 0..1 mastery = P(correct on an average-difficulty item)."""
    return float(1.0 / (1.0 + np.exp(-theta)))


def per_concept_mastery(df: pd.DataFrame, scale: float = 4.0, prior_sd: float = 1.6) -> dict[str, float]:
    """Per-concept mastery via online IRT, difficulty-aware.

    Requires columns `skill`, `correct`, and `difficulty`. Falls back to raw accuracy for
    any concept missing difficulties. Returns {concept: mastery in [0,1]}.
    """
    if not {"skill", "correct"}.issubset(df.columns):
        return {}
    out: dict[str, float] = {}
    has_diff = "difficulty" in df.columns
    for skill, grp in df.groupby("skill"):
        y = grp["correct"].to_numpy(dtype=float)
        if has_diff and grp["difficulty"].notna().all():
            b = grp["difficulty"].map(lambda d: bank_difficulty_to_b(d, scale)).to_numpy()
            theta = estimate_ability(y, b, prior_sd=prior_sd)
            out[str(skill)] = ability_to_mastery(theta)
        else:
            out[str(skill)] = float(y.mean())  # graceful fallback
    return out
