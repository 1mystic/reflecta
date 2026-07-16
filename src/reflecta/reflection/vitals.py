"""Cognitive-vitals emotion mapping - turn live model signals into a face expression.

The live quiz surfaces the online-IRT belief state after every answer (ability theta, its
posterior certainty, running calibration and timing). `face_emotion` collapses those real
signals into one of a small set of expressions the SVG face renders. It is a pure,
deterministic function of the signals - the face never invents a mood, it only reports what
the numbers already say. The thresholds are documented inline so the mapping is auditable.

Emotions (most specific wins, checked in order):
  overconfident : confidently wrong - fast-wrong pattern OR strongly overconfident calibration
  struggling    : mostly wrong and slow - low mastery with effort
  confused      : memorization without transfer - reworded probes drop accuracy
  confident     : high mastery AND the model is sure (tight posterior)
  flow          : on a correct streak, moving well
  calm          : the neutral default / cold start
"""
from __future__ import annotations

EMOTIONS = ("calm", "flow", "confident", "confused", "overconfident", "struggling")


def face_emotion(
    *,
    mastery: float,
    certainty: float,
    calib_direction: float | None,
    timing_profile: dict | None,
    transfer_max: float | None,
    streak: int,
    n_answered: int,
) -> str:
    """Map live vitals to one expression. See module docstring for the signal semantics.

    - mastery in [0,1] (P(correct on an average item) from theta)
    - certainty in [0,1] (how far the posterior has tightened past the prior)
    - calib_direction: conf.mean - acc.mean; > 0 overconfident, < 0 underconfident, None if
      confidence not captured yet
    - timing_profile: fast/slow x correct/wrong quadrant fractions (may be {})
    - transfer_max: largest per-concept acc(original)-acc(reworded) gap seen (None if no
      reworded probes answered yet)
    - streak: current run of consecutive correct answers
    - n_answered: total answers so far (cold start when small)
    """
    if n_answered < 1:
        return "calm"

    tp = timing_profile or {}
    fast_wrong = tp.get("fast_wrong", 0.0)

    # confidently wrong beats everything - it's the signal most worth surfacing
    if fast_wrong >= 0.34 or (calib_direction is not None and calib_direction >= 0.25):
        return "overconfident"

    # low mastery with real effort (slow and wrong) - the learner is stuck, not careless
    if mastery < 0.4 and tp.get("slow_wrong", 0.0) >= 0.25:
        return "struggling"

    # memorization without transfer - recognizes phrasing, accuracy collapses when reworded
    if transfer_max is not None and transfer_max >= 0.4:
        return "confused"

    # high mastery AND the model is sure about it (needs accumulated, consistent evidence)
    if mastery >= 0.7 and certainty >= 0.35:
        return "confident"

    # moving well: a live correct streak
    if streak >= 3:
        return "flow"

    return "calm"
