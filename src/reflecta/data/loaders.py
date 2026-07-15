"""Loaders that normalize public datasets into Reflecta's canonical schema.

Canonical long-format columns:
    learner_id, item_id, skill, correct, response_time, chosen_option,
    confidence, paraphrase_group, is_reworded

Public logs fill what they have; missing columns are left absent (features degrade to NaN).
Implement each loader against files placed in data/raw/ by scripts/download_data.py.
"""
from __future__ import annotations

import pandas as pd

from reflecta.config import CONFIG

CANONICAL = [
    "learner_id", "item_id", "skill", "correct", "response_time",
    "chosen_option", "confidence", "paraphrase_group", "is_reworded",
]


def load_assistments(filename: str = "assistments_2009.csv") -> pd.DataFrame:
    """ASSISTments 2009 skill-builder -> canonical schema.

    Column mapping (typical ASSISTments export):
        user_id -> learner_id, problem_id -> item_id, skill_name -> skill,
        correct -> correct, ms_first_response -> response_time (seconds)
    """
    path = CONFIG.paths.raw / filename
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run: python scripts/download_data.py --dataset assistments"
        )
    df = pd.read_csv(path, encoding="latin-1", low_memory=False)
    out = pd.DataFrame({
        "learner_id": df.get("user_id"),
        "item_id": df.get("problem_id"),
        "skill": df.get("skill_name"),
        "correct": df.get("correct"),
        "response_time": df.get("ms_first_response", pd.Series(dtype=float)) / 1000.0,
    })
    return out.dropna(subset=["learner_id", "correct"]).reset_index(drop=True)


def load_eedi(filename: str = "eedi_answers.csv") -> pd.DataFrame:
    """Eedi diagnostic answers -> canonical schema (carries chosen_option for signal #2)."""
    path = CONFIG.paths.raw / filename
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. See data/README.md for the Eedi download."
        )
    df = pd.read_csv(path)
    return pd.DataFrame({
        "learner_id": df.get("UserId"),
        "item_id": df.get("QuestionId"),
        "correct": df.get("IsCorrect"),
        "chosen_option": df.get("AnswerValue"),
    })
