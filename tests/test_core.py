"""Core sanity tests — run with:  pytest -q"""
import numpy as np

from reflecta.data.synthetic import generate_cohort, generate_learner_log
from reflecta.eval.metrics import brier_score, expected_calibration_error, next_question_auc
from reflecta.features.behavior import extract_behavior_signals, per_skill_mastery
from reflecta.models.intent_gap import IntentGapMapper
from reflecta.models.irt import IRT1PL
from reflecta.models.knowledge_tracing import BKT


def test_irt_recovers_ability_ordering():
    """A higher-ability learner should get a higher fitted theta."""
    cohort = generate_cohort(n_learners=30, seed=1)
    lid = cohort["learner_id"].to_numpy()
    item = (cohort["skill"].astype(str) + cohort["item_id"].astype(str)).astype("category").cat.codes.to_numpy()
    y = cohort["correct"].to_numpy()
    irt = IRT1PL(n_learners=lid.max() + 1, n_items=item.max() + 1).fit(lid, item, y, epochs=200)
    # correlation between fitted ability and each learner's raw accuracy should be positive
    acc = cohort.groupby("learner_id")["correct"].mean().sort_index().to_numpy()
    corr = np.corrcoef(irt.theta[: len(acc)], acc)[0, 1]
    assert corr > 0.5


def test_memorization_index_detects_memorizer():
    mem = generate_learner_log(learner_id=1, memorizer=True, seed=3)
    non = generate_learner_log(learner_id=2, memorizer=False, seed=3)
    assert extract_behavior_signals(mem)["memorization_index"] > \
           extract_behavior_signals(non)["memorization_index"]


def test_calibration_metrics_bounds():
    probs = np.array([0.9, 0.8, 0.2, 0.1])
    out = np.array([1, 1, 0, 0])
    assert 0.0 <= expected_calibration_error(probs, out) <= 1.0
    assert 0.0 <= brier_score(probs, out) <= 1.0
    assert next_question_auc(probs, out) == 1.0  # perfectly separable


def test_intent_gap_report():
    df = generate_learner_log(learner_id=1, memorizer=True, seed=5)
    mastery = per_skill_mastery(df)
    report = IntentGapMapper().analyze("data science interview", mastery)
    assert 0.0 <= report.readiness <= 1.0
    assert report.top_gaps  # non-empty
    assert report.top_gaps[0].gap >= report.top_gaps[-1].gap  # sorted


def test_bkt_mastery_monotonic_on_all_correct():
    bkt = BKT()
    m_few = bkt.mastery([1, 1])
    m_many = bkt.mastery([1, 1, 1, 1, 1])
    assert m_many >= m_few


def test_online_ability_monotonic():
    from reflecta.models.online_irt import estimate_ability
    b = np.zeros(4)  # average-difficulty items
    theta_low = estimate_ability(np.array([0, 0, 0, 1]), b)
    theta_high = estimate_ability(np.array([1, 1, 1, 0]), b)
    assert theta_high > theta_low
    # prior keeps all-correct finite
    assert abs(estimate_ability(np.array([1, 1, 1]), np.zeros(3))) < 4.0


def test_online_ability_is_difficulty_aware():
    """Same score, but the harder items should imply higher ability."""
    from reflecta.models.online_irt import bank_difficulty_to_b, estimate_ability
    y = np.array([1, 1, 0, 0])
    easy_b = np.array([bank_difficulty_to_b(d) for d in [0.2, 0.2, 0.2, 0.2]])
    hard_b = np.array([bank_difficulty_to_b(d) for d in [0.8, 0.8, 0.8, 0.8]])
    assert estimate_ability(y, hard_b) > estimate_ability(y, easy_b)


def test_per_concept_mastery_uses_difficulty():
    import pandas as pd
    from reflecta.models.online_irt import per_concept_mastery
    df = pd.DataFrame({
        "skill": ["sql"] * 4,
        "correct": [1, 1, 1, 0],
        "difficulty": [0.6, 0.6, 0.6, 0.6],
    })
    m = per_concept_mastery(df)
    assert "sql" in m and 0.0 <= m["sql"] <= 1.0
