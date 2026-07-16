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


def estimate_ability_var(
    correct: np.ndarray, b: np.ndarray, prior_sd: float = 1.6, iters: int = 50
) -> tuple[float, float]:
    """MAP estimate of theta AND its Laplace posterior variance, given fixed difficulties b.

    Newton's method already forms the negative log-posterior Hessian each step; the Laplace
    posterior variance of theta is exactly -1/hess (Fisher information Σ p(1-p) plus the
    prior precision 1/σ²). With no responses the posterior equals the prior, so the variance
    is the prior variance σ². The variance shrinks as consistent evidence accumulates — this
    is the "the model is getting surer about you" signal the live UI visualizes.

    Returns (theta, var_theta). var_theta is always finite and > 0.
    """
    y = np.asarray(correct, dtype=float)
    b = np.asarray(b, dtype=float)
    prior_var = prior_sd ** 2
    if len(y) == 0:
        return 0.0, float(prior_var)  # posterior == prior
    theta = 0.0
    inv_var = 1.0 / prior_var
    hess = -inv_var  # fallback if the loop never runs (iters<=0)
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-(theta - b)))
        grad = np.sum(y - p) - theta * inv_var
        hess = -np.sum(p * (1 - p)) - inv_var  # < 0 always (both terms negative)
        step = grad / hess
        theta -= step
        theta = float(np.clip(theta, -4.0, 4.0))
        if abs(step) < 1e-6:
            break
    var_theta = -1.0 / hess  # hess < 0, so this is > 0
    return theta, float(var_theta)


def estimate_ability(
    correct: np.ndarray, b: np.ndarray, prior_sd: float = 1.6, iters: int = 50
) -> float:
    """MAP estimate of a single learner's ability theta given fixed item difficulties b.

    Thin wrapper over estimate_ability_var for callers that only need the point estimate
    (e.g. per_concept_mastery, the MasteryEstimator Protocol).
    """
    theta, _ = estimate_ability_var(correct, b, prior_sd=prior_sd, iters=iters)
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


def variance_to_certainty(var_theta: float, prior_sd: float = 1.6) -> float:
    """Map posterior variance of theta to a 0..1 "certainty" the UI can show as a bar.

    Anchored to the prior: at cold start (var == prior variance) certainty is 0, and it
    rises toward 1 as the posterior tightens. Uses the ratio of precisions so it's a true
    "how much has evidence sharpened the belief beyond the prior" reading, not an arbitrary
    squash: certainty = 1 - var/prior_var = evidence_precision / total_precision.
    """
    prior_var = prior_sd ** 2
    if var_theta <= 0:
        return 1.0
    return float(np.clip(1.0 - var_theta / prior_var, 0.0, 1.0))


def session_vitals(df: pd.DataFrame, scale: float = 4.0, prior_sd: float = 1.6) -> dict:
    """Live "cognitive vitals" for one in-progress or finished session.

    Bundles the real latent-trait quantities the UI dramatizes: overall ability theta with
    its posterior variance + derived certainty, overall mastery, and per-concept
    mastery/theta plus the per-concept transfer (memorization) gap. Everything here is a
    genuine model quantity, not decoration. Degrades gracefully (theta 0, certainty 0) on an
    empty or column-poor DataFrame.
    """
    # local import avoids any import-order coupling; behavior.py has no dep on this module
    from reflecta.features.behavior import per_concept_transfer

    if "correct" not in df.columns or len(df) == 0:
        return {
            "theta": 0.0, "var_theta": float(prior_sd ** 2), "certainty": 0.0,
            "mastery": 0.5, "per_concept": {}, "transfer": {}, "n_answered": int(len(df)),
        }

    y = df["correct"].to_numpy(dtype=float)
    has_diff = "difficulty" in df.columns and df["difficulty"].notna().all()
    if has_diff:
        b = df["difficulty"].map(lambda d: bank_difficulty_to_b(d, scale)).to_numpy()
    else:
        b = np.zeros(len(y))  # unknown difficulty => treat as average-difficulty items
    theta, var_theta = estimate_ability_var(y, b, prior_sd=prior_sd)

    per_concept: dict[str, dict] = {}
    if "skill" in df.columns:
        for skill, grp in df.groupby("skill"):
            gy = grp["correct"].to_numpy(dtype=float)
            if has_diff:
                gb = grp["difficulty"].map(lambda d: bank_difficulty_to_b(d, scale)).to_numpy()
            else:
                gb = np.zeros(len(gy))
            c_theta, _ = estimate_ability_var(gy, gb, prior_sd=prior_sd)
            per_concept[str(skill)] = {
                "mastery": ability_to_mastery(c_theta), "theta": round(c_theta, 3),
            }

    return {
        "theta": round(theta, 3),
        "var_theta": round(var_theta, 3),
        "certainty": round(variance_to_certainty(var_theta, prior_sd), 3),
        "mastery": round(ability_to_mastery(theta), 3),
        "per_concept": per_concept,
        "transfer": per_concept_transfer(df),
        "n_answered": int(len(df)),
    }
