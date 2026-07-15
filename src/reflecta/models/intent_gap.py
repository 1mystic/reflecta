"""Intent -> Gap mapping — the hero capability.

The question this answers: *"You told me why you're learning. Is what you're mastering
actually moving you toward that goal, or are you grinding the wrong things?"*

Pipeline
--------
1. GOAL -> REQUIREMENT vector `r`: how much each concept matters for the stated goal,
   and the target mastery level it demands. In production this comes from an LLM
   goal-decomposition (free/local) or a curated goal->skill map; here it's pluggable.
2. LEARNER -> MASTERY vector `m` over the same concepts (from IRT ability per concept,
   or KT mastery), scaled to [0, 1].
3. GAP = requirement-weighted shortfall per concept:
        gap_c = importance_c * max(0, target_c - m_c)
   Plus two derived diagnostics:
        - readiness  : how close overall mastery is to what the goal needs
        - misallocation : effort spent on concepts the goal barely needs
          (surfaces "you're memorizing trivia the goal doesn't require")

Everything here is transparent arithmetic on named concepts — deliberately so, because
the *explanation* is the product. No black box between signal and reflection.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConceptRequirement:
    concept: str
    importance: float  # 0..1 weight of this concept for the goal
    target: float = 0.8  # mastery level (0..1) the goal demands


@dataclass
class GapItem:
    concept: str
    importance: float
    target: float
    mastery: float
    gap: float  # importance-weighted shortfall


@dataclass
class GapReport:
    goal: str
    readiness: float  # 0..1, weighted mastery / weighted target
    items: list[GapItem] = field(default_factory=list)
    misallocation: list[str] = field(default_factory=list)  # over-practiced, low-need concepts

    @property
    def top_gaps(self) -> list[GapItem]:
        return sorted(self.items, key=lambda g: g.gap, reverse=True)


class IntentGapMapper:
    """Maps a stated goal + a learner's mastery into an actionable gap report.

    `goal_resolver` turns a free-text goal into a list of ConceptRequirement. The
    default is a small curated library; plug in an LLM-backed resolver for open goals.
    """

    def __init__(self, goal_resolver=None):
        self.goal_resolver = goal_resolver or self._default_resolver

    def analyze(
        self,
        goal: str,
        mastery: dict[str, float],
        effort: dict[str, float] | None = None,
        requirements: list[ConceptRequirement] | None = None,
    ) -> GapReport:
        """`requirements` overrides the resolver — used when a generated topic bank
        already carries goal-specific concept requirements (from the Claude API)."""
        reqs = requirements if requirements else self.goal_resolver(goal)
        items: list[GapItem] = []
        weighted_mastery = 0.0
        weighted_target = 0.0
        required_concepts = {r.concept for r in reqs}
        for r in reqs:
            m = float(mastery.get(r.concept, 0.0))
            gap = r.importance * max(0.0, r.target - m)
            items.append(GapItem(r.concept, r.importance, r.target, m, gap))
            weighted_mastery += r.importance * min(m, r.target)
            weighted_target += r.importance * r.target
        readiness = (weighted_mastery / weighted_target) if weighted_target else 0.0

        # misallocation: concepts the learner spends real effort on but the goal
        # barely needs (importance ~0 or not required at all).
        misallocation: list[str] = []
        if effort:
            req_importance = {r.concept: r.importance for r in reqs}
            median_effort = sorted(effort.values())[len(effort) // 2] if effort else 0
            for concept, e in effort.items():
                if e >= median_effort and req_importance.get(concept, 0.0) < 0.15:
                    misallocation.append(concept)

        return GapReport(
            goal=goal,
            readiness=round(readiness, 4),
            items=items,
            misallocation=misallocation,
        )

    # --- default curated resolver (demo / cold-start) ---
    @staticmethod
    def _default_resolver(goal: str) -> list[ConceptRequirement]:
        g = goal.lower()
        library: dict[str, list[ConceptRequirement]] = {
            "data science interview": [
                ConceptRequirement("probability", 0.9, 0.85),
                ConceptRequirement("linear_algebra", 0.7, 0.75),
                ConceptRequirement("sql", 0.8, 0.8),
                ConceptRequirement("ml_fundamentals", 1.0, 0.85),
                ConceptRequirement("trivia_history", 0.05, 0.3),
            ],
            "neet biology": [
                ConceptRequirement("cell_biology", 1.0, 0.9),
                ConceptRequirement("genetics", 0.9, 0.85),
                ConceptRequirement("human_physiology", 1.0, 0.9),
                ConceptRequirement("ecology", 0.6, 0.7),
            ],
        }
        for key, reqs in library.items():
            if all(tok in g for tok in key.split()):
                return reqs
        # generic fallback: single lumped concept
        return [ConceptRequirement("general", 1.0, 0.8)]
