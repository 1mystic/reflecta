"""Pydantic request/response models for the Reflecta API."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


# ---------- legacy persona-demo analyze ----------
class Interaction(BaseModel):
    skill: str
    correct: int = Field(ge=0, le=1)
    response_time: float | None = None
    chosen_option: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    paraphrase_group: str | None = None
    is_reworded: int | None = Field(default=None, ge=0, le=1)


class AnalyzeRequest(BaseModel):
    goal: str = "data science interview"
    interactions: list[Interaction] = []
    demo_persona: str | None = None


class GapItemOut(BaseModel):
    concept: str
    importance: float
    target: float
    mastery: float
    gap: float


class AnalyzeResponse(BaseModel):
    goal: str
    readiness: float
    overall_accuracy: float
    memorization_index: float | None
    timing_profile: dict
    calibration: dict
    gaps: list[GapItemOut]
    misallocation: list[str]
    reflection: list[str]


# ---------- live quiz flow ----------
class QuizStartRequest(BaseModel):
    goal: str = Field(default="data science interview")
    n_questions: int = Field(default=12, ge=2, le=40)
    consent: bool = Field(default=False, description="learner agrees to anonymous storage of responses")
    # opaque, client-generated id (e.g. crypto.randomUUID() in localStorage) — NOT an
    # account, no PII. Lets mastery accumulate across sessions. Omit for a one-off quiz.
    learner_id: str | None = Field(default=None, max_length=64)

    @field_validator("goal")
    @classmethod
    def _clean_goal(cls, v: str) -> str:
        # be forgiving: trim + truncate instead of rejecting with a 422
        v = (v or "").strip()[:200]
        return v or "general learning"

    @field_validator("learner_id")
    @classmethod
    def _clean_learner_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        safe = "".join(c for c in v if c.isalnum() or c == "-")
        return safe or None


class ServedQuestionOut(BaseModel):
    id: str
    concept: str
    stem: str
    options: dict[str, str]   # letter -> text (answer NOT included)
    is_reworded: int


class QuizStartResponse(BaseModel):
    session_id: str
    goal: str
    questions: list[ServedQuestionOut]
    learner_id: str  # echoed back so the client can persist it on first use


class AnswerIn(BaseModel):
    question_id: str
    chosen_letter: str
    response_time: float | None = None   # seconds, measured client-side
    confidence: float | None = Field(default=None, ge=0, le=1)


class QuizSubmitRequest(BaseModel):
    session_id: str
    answers: list[AnswerIn]


class GradedItem(BaseModel):
    question_id: str
    correct: int
    correct_letter: str
    chosen_letter: str | None
    explanation: str


class LearnerHistoryOut(BaseModel):
    n_sessions: int
    readiness_trend: list[float]   # oldest -> newest, one per prior session (this one included)
    score_trend: list[float]


class QuizSubmitResponse(BaseModel):
    session_id: str
    score: float                 # fraction correct
    graded: list[GradedItem]
    analysis: AnalyzeResponse
    history: LearnerHistoryOut | None = None  # present only when learner_id was supplied
