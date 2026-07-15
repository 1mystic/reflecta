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
