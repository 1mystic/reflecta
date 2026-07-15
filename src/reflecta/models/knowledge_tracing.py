"""Knowledge Tracing — mastery *over time* (signal #3).

Two rungs, interpretable first:

  BKT (Bayesian Knowledge Tracing)  -- implemented here as the baseline. A 2-state HMM
      per skill with parameters {p_init, p_transit, p_slip, p_guess}. Interpretable,
      cheap, and a strong reference point.

  SAKT / DKT (neural)               -- interface stub below; implement in a notebook with
      torch on free Kaggle/Colab GPU, then load weights here for serving.

Metric for both: next-question AUC (see reflecta.eval.metrics.next_question_auc).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class BKTParams:
    p_init: float = 0.2     # P(knows skill before any practice)
    p_transit: float = 0.1  # P(learn skill after an opportunity)
    p_slip: float = 0.1     # P(wrong | knows)
    p_guess: float = 0.2    # P(correct | doesn't know)


class BKT:
    """Single-skill Bayesian Knowledge Tracing.

    Fit per skill with EM (or a fixed grid search for a first pass). `predict_next`
    returns P(correct on next attempt) given a sequence of past correct/incorrect.
    """

    def __init__(self, params: BKTParams | None = None):
        self.p = params or BKTParams()

    def _posterior_known(self, p_known: float, correct: int) -> float:
        p, s, g = self.p, self.p.p_slip, self.p.p_guess
        if correct:
            num = p_known * (1 - s)
            den = num + (1 - p_known) * g
        else:
            num = p_known * s
            den = num + (1 - p_known) * (1 - g)
        post = num / den if den > 0 else p_known
        # learning transition after the opportunity
        return post + (1 - post) * self.p.p_transit

    def predict_sequence(self, responses: list[int]) -> list[float]:
        """Return P(correct) predicted *before* each attempt in the sequence."""
        p_known = self.p.p_init
        preds = []
        for r in responses:
            p_correct = p_known * (1 - self.p.p_slip) + (1 - p_known) * self.p.p_guess
            preds.append(p_correct)
            p_known = self._posterior_known(p_known, r)
        return preds

    def mastery(self, responses: list[int]) -> float:
        """Current P(knows skill) after observing `responses`."""
        p_known = self.p.p_init
        for r in responses:
            p_known = self._posterior_known(p_known, r)
        return float(p_known)

    def fit_grid(self, sequences: list[list[int]], grid: int = 6) -> "BKT":
        """Crude but reproducible fit: grid-search params maximizing log-likelihood.

        Good enough for a baseline; replace with EM for the writeup.
        """
        best_ll, best = -np.inf, self.p
        space = np.linspace(0.05, 0.45, grid)
        for pi in space:
            for pt in space:
                for ps in space:
                    for pg in space:
                        self.p = BKTParams(pi, pt, ps, pg)
                        ll = 0.0
                        for seq in sequences:
                            preds = self.predict_sequence(seq)
                            for pr, r in zip(preds, seq):
                                pr = min(max(pr, 1e-6), 1 - 1e-6)
                                ll += r * np.log(pr) + (1 - r) * np.log(1 - pr)
                        if ll > best_ll:
                            best_ll, best = ll, self.p
        self.p = best
        return self


class NeuralKT:
    """Interface stub for SAKT/DKT — implement/train in notebooks, serve here.

    Kept as a stub so the core package installs light. See
    notebooks/02_knowledge_tracing.ipynb for the torch training loop.
    """

    def __init__(self, checkpoint: str | None = None):
        self.checkpoint = checkpoint
        raise NotImplementedError(
            "Train SAKT/DKT in notebooks/02_knowledge_tracing.ipynb, then load here."
        )
