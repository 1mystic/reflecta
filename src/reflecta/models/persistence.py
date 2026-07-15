"""Persist / load fitted models as plain JSON — deploy-friendly, no pickle security risk.

Artifacts land in models_store/ (inside this repo). The API loads them at startup if
present; otherwise it degrades to online estimation from the bank difficulties.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from reflecta.config import CONFIG
from reflecta.models.irt import IRT1PL
from reflecta.models.knowledge_tracing import BKT, BKTParams

STORE = CONFIG.paths.models_store


def _ensure_store() -> Path:
    STORE.mkdir(parents=True, exist_ok=True)
    return STORE


def save_irt(model: IRT1PL, name: str = "irt_1pl") -> Path:
    path = _ensure_store() / f"{name}.json"
    payload = {
        "type": "IRT1PL",
        "n_learners": model.n_learners,
        "n_items": model.n_items,
        "theta": model.theta.tolist(),
        "b": model.b.tolist(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def load_irt(name: str = "irt_1pl") -> IRT1PL | None:
    path = STORE / f"{name}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    m = IRT1PL(n_learners=d["n_learners"], n_items=d["n_items"])
    m.theta = np.asarray(d["theta"])
    m.b = np.asarray(d["b"])
    return m


def save_bkt(models: dict[str, BKT], name: str = "bkt_per_skill") -> Path:
    path = _ensure_store() / f"{name}.json"
    payload = {
        skill: bkt.p.__dict__ for skill, bkt in models.items()
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def load_bkt(name: str = "bkt_per_skill") -> dict[str, BKT] | None:
    path = STORE / f"{name}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    return {skill: BKT(BKTParams(**params)) for skill, params in d.items()}
