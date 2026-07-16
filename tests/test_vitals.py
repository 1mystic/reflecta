"""Cognitive-vitals regression tests: posterior variance, per-concept transfer, and the
deterministic face-emotion mapping. These guard the real model quantities the live UI shows
- if any of these drift, the "model getting surer / confidently wrong" story silently breaks.
"""
import numpy as np
import pandas as pd

from reflecta.features.behavior import per_concept_transfer
from reflecta.models.online_irt import (
    estimate_ability_var,
    session_vitals,
    variance_to_certainty,
)
from reflecta.reflection.vitals import face_emotion


def test_variance_is_prior_at_cold_start_and_shrinks_with_evidence():
    prior_sd = 1.6
    # no responses => posterior equals the prior (variance == prior variance)
    theta0, var0 = estimate_ability_var(np.array([]), np.array([]), prior_sd=prior_sd)
    assert theta0 == 0.0
    assert var0 == prior_sd ** 2

    # variance must strictly shrink as consistent evidence accumulates
    prev = var0
    for n in (1, 2, 4, 8):
        _, var = estimate_ability_var(np.ones(n), np.zeros(n), prior_sd=prior_sd)
        assert var > 0
        assert var < prev, f"variance did not shrink at n={n}"
        prev = var


def test_certainty_is_zero_at_prior_and_rises():
    prior_sd = 1.6
    assert variance_to_certainty(prior_sd ** 2, prior_sd) == 0.0  # no evidence yet
    assert variance_to_certainty(0.0, prior_sd) == 1.0            # perfect certainty
    # a tighter posterior reads as higher certainty
    assert variance_to_certainty(0.5, prior_sd) > variance_to_certainty(1.5, prior_sd)


def test_session_vitals_shape_and_transfer():
    df = pd.DataFrame({
        "skill": ["a", "a", "b", "b"],
        "correct": [1, 0, 1, 1],
        "difficulty": [0.3, 0.7, 0.5, 0.9],
        "is_reworded": [0, 1, 0, 1],
    })
    v = session_vitals(df)
    assert set(v) >= {"theta", "var_theta", "certainty", "mastery", "per_concept",
                      "transfer", "n_answered"}
    assert 0.0 <= v["certainty"] <= 1.0
    assert 0.0 <= v["mastery"] <= 1.0
    assert v["n_answered"] == 4
    # concept a: original right, reworded wrong => transfer gap of 1.0 (memorized)
    assert v["transfer"]["a"] == 1.0
    # concept b: original right, reworded right => no gap
    assert v["transfer"]["b"] == 0.0


def test_session_vitals_empty_is_safe():
    v = session_vitals(pd.DataFrame({"correct": []}))
    assert v["theta"] == 0.0 and v["certainty"] == 0.0 and v["n_answered"] == 0


def test_per_concept_transfer_omits_incomplete_concepts():
    # concept c has only an original probe -> no defined transfer -> omitted
    df = pd.DataFrame({
        "skill": ["a", "a", "c"],
        "correct": [1, 0, 1],
        "is_reworded": [0, 1, 0],
    })
    t = per_concept_transfer(df)
    assert "a" in t and "c" not in t


def test_face_emotion_boundaries():
    base = dict(mastery=0.6, certainty=0.5, calib_direction=0.0,
                timing_profile={}, transfer_max=None, streak=0, n_answered=5)

    # cold start
    assert face_emotion(**{**base, "n_answered": 0}) == "calm"
    # confidently wrong via fast_wrong quadrant
    assert face_emotion(**{**base, "timing_profile": {"fast_wrong": 0.5}}) == "overconfident"
    # confidently wrong via overconfident calibration direction
    assert face_emotion(**{**base, "calib_direction": 0.3}) == "overconfident"
    # struggling: low mastery + slow-and-wrong
    assert face_emotion(**{**base, "mastery": 0.2,
                           "timing_profile": {"slow_wrong": 0.4}}) == "struggling"
    # memorization without transfer
    assert face_emotion(**{**base, "transfer_max": 0.5}) == "confused"
    # confident: high mastery + the model is sure
    assert face_emotion(**{**base, "mastery": 0.8, "certainty": 0.5}) == "confident"
    # flow: a correct streak short of "confident"
    assert face_emotion(**{**base, "mastery": 0.6, "certainty": 0.1, "streak": 4}) == "flow"
