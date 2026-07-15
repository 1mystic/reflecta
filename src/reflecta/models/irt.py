"""Item Response Theory — the principled basis for "mastery".

1PL (Rasch): P(correct | learner i, item j) = sigmoid(theta_i - b_j)
  theta_i : ability of learner i        (what we surface as mastery)
  b_j     : difficulty of item j

Fit by maximum likelihood via simple full-batch gradient ascent — no heavy deps,
fully reproducible, and enough to recover abilities on real KT logs. Swap in a
2PL (add discrimination a_j) once the pipeline is validated.

Why IRT and not raw % correct? Because % correct conflates *how hard the items were*
with *how able the learner is*. IRT separates them, so "mastery" is comparable across
learners who saw different questions — essential for intent->gap mapping.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


@dataclass
class IRT1PL:
    n_learners: int
    n_items: int
    lr: float = 0.1
    l2: float = 1e-3
    seed: int = 42

    def __post_init__(self) -> None:
        rng = np.random.default_rng(self.seed)
        self.theta = rng.normal(0, 0.1, self.n_learners)  # abilities
        self.b = rng.normal(0, 0.1, self.n_items)         # difficulties
        self.history_: list[float] = []

    def fit(
        self,
        learner_idx: np.ndarray,
        item_idx: np.ndarray,
        correct: np.ndarray,
        epochs: int = 200,
    ) -> "IRT1PL":
        """Fit on long-format interactions (one row per answered item)."""
        learner_idx = np.asarray(learner_idx)
        item_idx = np.asarray(item_idx)
        y = np.asarray(correct, dtype=float)
        n = len(y)
        for _ in range(epochs):
            logits = self.theta[learner_idx] - self.b[item_idx]
            p = _sigmoid(logits)
            err = y - p  # dLL/dlogit
            # accumulate per-parameter gradients
            g_theta = np.zeros_like(self.theta)
            g_b = np.zeros_like(self.b)
            np.add.at(g_theta, learner_idx, err)
            np.add.at(g_b, item_idx, -err)
            self.theta += self.lr * (g_theta / n - self.l2 * self.theta)
            self.b += self.lr * (g_b / n - self.l2 * self.b)
            # track log-likelihood
            eps = 1e-9
            ll = np.mean(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))
            self.history_.append(float(ll))
        return self

    def predict_proba(self, learner_idx: np.ndarray, item_idx: np.ndarray) -> np.ndarray:
        return _sigmoid(self.theta[np.asarray(learner_idx)] - self.b[np.asarray(item_idx)])

    def ability(self, learner_idx: int) -> float:
        return float(self.theta[learner_idx])
