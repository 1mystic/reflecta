"""End-to-end sanity demo — runs today, no downloads, no API keys.

    python -m reflecta.demo

Generates a synthetic cohort, fits IRT, extracts behavior signals for one learner,
runs intent->gap mapping, prints a reflection, and logs a couple of metrics through the
tracking wrapper (console backend by default).
"""
from __future__ import annotations

import numpy as np

from reflecta.data.synthetic import generate_cohort, generate_learner_log
from reflecta.eval.metrics import brier_score, expected_calibration_error, next_question_auc
from reflecta.features.behavior import confidence_pairs, extract_behavior_signals, per_skill_mastery
from reflecta.models.intent_gap import IntentGapMapper
from reflecta.models.irt import IRT1PL
from reflecta.reflection.engine import generate_reflection
from reflecta.tracking.experiment import track


def main() -> None:
    print("=" * 70)
    print("Reflecta end-to-end demo")
    print("=" * 70)

    # 1) synthetic cohort -> fit IRT to recover abilities
    cohort = generate_cohort(n_learners=40, seed=42)
    learner_ids = cohort["learner_id"].to_numpy()
    item_key = (cohort["skill"].astype(str) + "_" + cohort["item_id"].astype(str))
    item_ids = item_key.astype("category").cat.codes.to_numpy()
    correct = cohort["correct"].to_numpy()

    irt = IRT1PL(n_learners=learner_ids.max() + 1, n_items=item_ids.max() + 1)
    irt.fit(learner_ids, item_ids, correct, epochs=300)
    p = irt.predict_proba(learner_ids, item_ids)
    auc = next_question_auc(p, correct)
    print(f"\n[IRT] fit AUC={auc:.3f}  |  final LL={irt.history_[-1]:.4f}")

    # 2) focus on one 'memorizer + overconfident' learner
    learner = generate_learner_log(learner_id=999, n_items=80,
                                   memorizer=True, overconfident=True, seed=7)
    signals = extract_behavior_signals(learner)
    print("\n[behavior signals]")
    print(f"  overall accuracy   : {signals['overall_accuracy']:.2f}")
    print(f"  memorization index : {signals['memorization_index']:.2f}  (>0 => weak transfer)")
    print(f"  timing profile     : {signals['timing_profile']}")

    # 3) calibration (confidence vs correctness)
    conf, corr = confidence_pairs(learner)
    ece = expected_calibration_error(conf, corr)
    brier = brier_score(conf, corr)
    print(f"\n[calibration] ECE={ece:.3f}  Brier={brier:.3f}  (high ECE => Dunning-Kruger)")

    # 4) intent -> gap
    mastery = per_skill_mastery(learner)
    effort = learner["skill"].value_counts(normalize=True).to_dict()
    gap = IntentGapMapper().analyze("data science interview", mastery, effort)
    print(f"\n[intent->gap] goal='{gap.goal}'  readiness={gap.readiness:.0%}")
    for g in gap.top_gaps[:3]:
        print(f"  - {g.concept:16s} mastery={g.mastery:.2f} target={g.target:.2f} gap={g.gap:.3f}")
    if gap.misallocation:
        print(f"  misallocated effort on: {gap.misallocation}")

    # 5) reflection
    print("\n[reflection]")
    for line in generate_reflection(signals, gap):
        print("  • " + line)

    # 6) log through the tracking wrapper
    with track("demo-e2e", config={"n_learners": 40, "model": "IRT1PL"}) as run:
        run.log({"irt/auc": float(auc), "calibration/ece": float(ece),
                 "calibration/brier": float(brier), "gap/readiness": float(gap.readiness)})

    print("\nDone. This is the skeleton every milestone builds on.")


if __name__ == "__main__":
    main()
