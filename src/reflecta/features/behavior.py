"""Behavior-signal extraction — turn raw interaction logs into metacognitive features.

Input: a long-format DataFrame, one row per answered item. Expected (nullable) columns:
    learner_id, item_id, skill, correct (0/1), response_time (s),
    chosen_option, confidence (0..1), paraphrase_group

Not every dataset has every column — features degrade gracefully to NaN when a source
signal is missing (e.g. ASSISTments has timing but no confidence; a quiz app can capture
confidence + paraphrase_group that public logs lack).

The interesting, Reflecta-specific features:
  - timing_profile        : fast-correct (fluent) vs slow-correct (effortful) vs
                            fast-wrong (misconception, answered confidently wrong)
  - memorization_index    : accuracy on *familiar* phrasings minus accuracy on
                            *reworded* items of the SAME concept (paraphrase_group).
                            High => recognizes surface form, hasn't transferred. (signal #1)
  - distractor_signature  : distribution over chosen wrong options per skill (signal #2 seed)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _safe(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col] if col in df.columns else pd.Series([np.nan] * len(df), index=df.index)


def per_skill_mastery(df: pd.DataFrame) -> dict[str, float]:
    """Raw accuracy per skill (a quick proxy; prefer IRT/BKT for real mastery)."""
    if "skill" not in df or "correct" not in df:
        return {}
    return df.groupby("skill")["correct"].mean().to_dict()


def timing_profile(df: pd.DataFrame) -> dict[str, float]:
    """Fractions of interactions in each (speed x correctness) quadrant.

    Speed split at the learner's median response time, so it's self-relative.
    """
    rt = _safe(df, "response_time").astype(float)
    correct = _safe(df, "correct").astype(float)
    valid = rt.notna() & correct.notna()
    if valid.sum() == 0:
        return {}
    rt, correct = rt[valid], correct[valid]
    fast = rt <= rt.median()
    n = len(rt)
    return {
        "fast_correct": float(((fast) & (correct == 1)).sum() / n),   # fluent
        "slow_correct": float(((~fast) & (correct == 1)).sum() / n),  # effortful
        "fast_wrong": float(((fast) & (correct == 0)).sum() / n),     # confident misconception
        "slow_wrong": float(((~fast) & (correct == 0)).sum() / n),    # struggling
    }


def memorization_index(df: pd.DataFrame) -> float:
    """accuracy(familiar phrasing) - accuracy(reworded phrasing) of the same concept.

    Requires a `paraphrase_group` column (concept id shared across rephrasings) and a
    `is_reworded` flag (0 = original/most-seen phrasing, 1 = transfer probe). Returns NaN
    when the signal isn't present. Positive => memorization without transfer.
    """
    if "paraphrase_group" not in df or "correct" not in df or "is_reworded" not in df:
        return float("nan")
    fam = df[df["is_reworded"] == 0]["correct"].mean()
    new = df[df["is_reworded"] == 1]["correct"].mean()
    if pd.isna(fam) or pd.isna(new):
        return float("nan")
    return float(fam - new)


def per_concept_transfer(df: pd.DataFrame) -> dict[str, float]:
    """Per-concept version of the memorization index: acc(original) - acc(reworded).

    Same signal as `memorization_index` but grouped by `skill`, so the UI can show which
    concepts are memorized-without-transfer rather than one session-wide scalar. A concept
    only appears when it has at least one original AND one reworded probe with a defined
    accuracy on each; concepts missing the signal are simply omitted. Empty dict when the
    paraphrase columns aren't present.
    """
    if not {"skill", "correct", "is_reworded"}.issubset(df.columns):
        return {}
    out: dict[str, float] = {}
    for skill, grp in df.groupby("skill"):
        fam = grp[grp["is_reworded"] == 0]["correct"].mean()
        new = grp[grp["is_reworded"] == 1]["correct"].mean()
        if pd.isna(fam) or pd.isna(new):
            continue
        out[str(skill)] = float(fam - new)
    return out


def distractor_signature(df: pd.DataFrame) -> dict[str, dict]:
    """Per-skill distribution over chosen options on *incorrect* answers.

    A peaked distribution (one distractor dominates) is a strong misconception signal —
    later joined against Eedi's misconception labels (signal #2).
    """
    if "skill" not in df or "chosen_option" not in df or "correct" not in df:
        return {}
    wrong = df[df["correct"] == 0]
    out: dict[str, dict] = {}
    for skill, grp in wrong.groupby("skill"):
        counts = grp["chosen_option"].value_counts(normalize=True).to_dict()
        out[str(skill)] = {str(k): round(float(v), 3) for k, v in counts.items()}
    return out


def confidence_pairs(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Return (confidence, correct) arrays for calibration metrics (signal #3).

    Empty arrays when confidence wasn't captured (public logs); the quiz app supplies it.
    """
    conf = _safe(df, "confidence").astype(float)
    correct = _safe(df, "correct").astype(float)
    valid = conf.notna() & correct.notna()
    return conf[valid].to_numpy(), correct[valid].to_numpy()


def extract_behavior_signals(df: pd.DataFrame) -> dict:
    """Convenience: bundle all behavior signals for one learner's interaction log."""
    return {
        "n_interactions": int(len(df)),
        "overall_accuracy": float(_safe(df, "correct").astype(float).mean()),
        "per_skill_mastery": per_skill_mastery(df),
        "timing_profile": timing_profile(df),
        "memorization_index": memorization_index(df),
        "distractor_signature": distractor_signature(df),
    }
