"""API-level tests — production behaviors: consent gate, no answer leak, erasure, ops."""
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health_and_ready():
    assert client.get("/api/health").json()["status"] == "ok"
    r = client.get("/api/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"


def test_model_info_lists_estimator():
    info = client.get("/api/model/info").json()
    assert "live_mastery_estimator" in info


def test_consent_is_required():
    r = client.post("/api/quiz/start", json={"goal": "data science interview",
                                             "n_questions": 6, "consent": False})
    assert r.status_code == 403


def test_quiz_flow_and_no_answer_leak():
    start = client.post("/api/quiz/start", json={"goal": "data science interview",
                                                 "n_questions": 8, "consent": True})
    assert start.status_code == 200
    data = start.json()
    # correct answers must never appear in the served payload
    for q in data["questions"]:
        assert "correct" not in q and "correct_letter" not in q

    answers = [{"question_id": q["id"], "chosen_letter": list(q["options"])[0],
                "response_time": 5.0, "confidence": 0.6} for q in data["questions"]]
    sub = client.post("/api/quiz/submit", json={"session_id": data["session_id"],
                                                "answers": answers})
    assert sub.status_code == 200
    body = sub.json()
    assert 0.0 <= body["score"] <= 1.0
    assert len(body["graded"]) == len(answers)
    assert "readiness" in body["analysis"]

    # right-to-erasure
    d = client.delete(f"/api/session/{data['session_id']}")
    assert d.status_code == 200 and d.json()["deleted"] == data["session_id"]


def test_submit_unknown_session_404():
    r = client.post("/api/quiz/submit", json={"session_id": "nope", "answers": []})
    assert r.status_code == 404


def test_learner_history_accumulates_across_sessions():
    import json as _json

    bank = _json.load(open("data/question_bank.json", encoding="utf-8"))["questions"]
    by_id = {q["id"]: q for q in bank}

    def take_quiz(learner_id=None):
        body = {"goal": "data science interview", "n_questions": 6, "consent": True}
        if learner_id:
            body["learner_id"] = learner_id
        start = client.post("/api/quiz/start", json=body).json()
        answers = []
        for q in start["questions"]:
            correct_text = by_id[q["id"]]["options"][by_id[q["id"]]["correct"]]
            letter = next(l for l, t in q["options"].items() if t == correct_text)
            answers.append({"question_id": q["id"], "chosen_letter": letter,
                            "response_time": 5.0, "confidence": 0.6})
        sub = client.post("/api/quiz/submit",
                          json={"session_id": start["session_id"], "answers": answers}).json()
        return start["learner_id"], sub

    lid, sub1 = take_quiz()
    assert sub1["history"] is None or sub1["history"]["n_sessions"] == 1
    lid2, sub2 = take_quiz(learner_id=lid)
    assert lid2 == lid
    assert sub2["history"]["n_sessions"] == 2
    assert len(sub2["history"]["readiness_trend"]) == 2


def test_goal_without_matching_bank_content_is_not_served_as_curated():
    """Regression: a goal can be in the intent-gap resolver's static library without any
    matching questions in the curated bank. Serving it as 'curated' would silently score
    mismatched questions (e.g. data-science items) against unrelated gap requirements
    (e.g. biology concepts). Without an API key configured, this must degrade to the
    explicit 503 for open-topic generation — never a 200 with mismatched content."""
    r = client.post("/api/quiz/start", json={"goal": "neet biology",
                                             "n_questions": 6, "consent": True})
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        # if a key IS configured in this environment, the served questions must be
        # relevant to biology, not the curated data-science bank
        stems = " ".join(q["stem"].lower() for q in r.json()["questions"])
        assert not any(kw in stems for kw in ("eigenvalue", "bayes", "left join"))
