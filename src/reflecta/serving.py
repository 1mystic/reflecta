"""Model serving layer — the seam between trained artifacts and live requests.

Two concerns:
  1. MasteryEstimator — how we turn a live session into per-concept mastery. The default,
     OnlineIRTMastery, works on the question bank today (item difficulties are known, the
     learner is new). A neural estimator (SAKT) becomes viable once we have enough *product*
     interaction data to train on the bank's exercise space — until then, serving SAKT
     trained on ASSISTments would be using the wrong exercise vocabulary, so we don't pretend.

  2. Model registry inspection — report which offline artifacts (IRT/BKT/SAKT) are present and
     their metadata, so /api/model/info can expose the deployed model versions.
"""
from __future__ import annotations

import json
from typing import Protocol

import pandas as pd

from reflecta.config import CONFIG
from reflecta.models.online_irt import per_concept_mastery


class MasteryEstimator(Protocol):
    name: str

    def estimate(self, session_df: pd.DataFrame) -> dict[str, float]:
        ...


class OnlineIRTMastery:
    """Difficulty-aware per-concept mastery for a live (cold-start) learner."""

    name = "online_irt_1pl"

    def estimate(self, session_df: pd.DataFrame) -> dict[str, float]:
        return per_concept_mastery(session_df)


def get_mastery_estimator() -> MasteryEstimator:
    """Factory — swap here when a product-trained neural estimator is available."""
    return OnlineIRTMastery()


def model_registry_info() -> dict:
    """Inspect models_store/ and report deployed artifacts + metadata."""
    store = CONFIG.paths.models_store
    info: dict = {"models": []}
    if not store.exists():
        return info

    irt = store / "irt_1pl.json"
    if irt.exists():
        d = json.loads(irt.read_text(encoding="utf-8"))
        info["models"].append({"name": "irt_1pl", "kind": "IRT-1PL",
                               "n_learners": d.get("n_learners"), "n_items": d.get("n_items")})
    bkt = store / "bkt_per_skill.json"
    if bkt.exists():
        d = json.loads(bkt.read_text(encoding="utf-8"))
        info["models"].append({"name": "bkt_per_skill", "kind": "BKT", "n_skills": len(d)})
    sakt = store / "sakt.pt"
    if sakt.exists():
        info["models"].append({"name": "sakt", "kind": "SAKT",
                               "size_kb": round(sakt.stat().st_size / 1024, 1)})

    info["live_mastery_estimator"] = get_mastery_estimator().name
    return info
