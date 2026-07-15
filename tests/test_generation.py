"""Tests for Claude-backed topic generation — no live API calls (client is mocked)."""
from unittest.mock import MagicMock, patch

from reflecta import generation


def _question(qid: str, correct: int, options=("A", "B", "C", "D")):
    return {"id": qid, "concept": "x", "difficulty": 0.5, "paraphrase_group": qid,
            "is_reworded": 0, "stem": f"stem {qid}", "options": list(options),
            "correct": correct, "explanation": "because"}


def _mock_response(answers: dict[str, int]):
    """Build a fake anthropic.messages.parse() response for _verify_bank."""
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.parsed_output.answers = [
        generation.VerifiedAnswer(id=qid, correct=c) for qid, c in answers.items()
    ]
    return resp


def test_verify_bank_keeps_agreeing_questions():
    questions = [_question("q1", correct=0), _question("q2", correct=2)]
    fake_client = MagicMock()
    fake_client.messages.parse.return_value = _mock_response({"q1": 0, "q2": 2})
    with patch("anthropic.Anthropic", return_value=fake_client):
        kept = generation._verify_bank(questions, model="claude-haiku-4-5")
    assert [q["id"] for q in kept] == ["q1", "q2"]


def test_verify_bank_drops_disagreeing_questions():
    """The core guard: if the independent pass disagrees, the question is dropped —
    mirrors the legacy project's discovery that ~25% of a human-authored bank had wrong keys."""
    questions = [_question("q1", correct=0), _question("q2", correct=2)]
    fake_client = MagicMock()
    # verifier disagrees with q2's marked answer (2 vs its own answer of 1)
    fake_client.messages.parse.return_value = _mock_response({"q1": 0, "q2": 1})
    with patch("anthropic.Anthropic", return_value=fake_client):
        kept = generation._verify_bank(questions, model="claude-haiku-4-5")
    assert [q["id"] for q in kept] == ["q1"]


def test_verify_bank_fails_open_on_refusal():
    """A safety refusal on the verification call must not silently empty the bank."""
    questions = [_question("q1", correct=0)]
    fake_client = MagicMock()
    refused = MagicMock()
    refused.stop_reason = "refusal"
    fake_client.messages.parse.return_value = refused
    with patch("anthropic.Anthropic", return_value=fake_client):
        kept = generation._verify_bank(questions, model="claude-haiku-4-5")
    assert kept == questions


def test_slugify_is_filesystem_safe():
    assert generation.slugify("Social Science: Study & Review!") == "social_science_study_review"
    assert generation.slugify("") == "topic"
