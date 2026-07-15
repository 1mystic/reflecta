"""Dynamic question generation — Claude-backed coverage for ANY topic.

The curated bank covers the data-science-interview concepts. When a learner brings a novel
goal ("social science study", "modern history", …), we generate a topic bank on the fly with
the Claude API (inspired by Episteme's approach: Claude as a structured pedagogy engine,
steered by deterministic scaffolding — not a free-form chat):

  - Claude proposes 3-5 concepts for the topic, with importance/target for the goal
    (feeds intent->gap directly)
  - MCQs per concept, each with an authored difficulty (feeds online IRT)
  - REWORDED TWINS for a subset (feeds the memorization signal)
  - distractors must encode plausible, specific misconceptions (feeds signal #2)

Generated banks are cached to data/generated_banks/{slug}.json so each topic costs one API
call ever. Without an ANTHROPIC_API_KEY the feature degrades gracefully: unknown topics get
a clear error explaining how to enable it — the curated bank keeps working regardless.

Uses the official `anthropic` SDK with structured outputs (`client.messages.parse` +
Pydantic), so the response is schema-validated by the API itself. Install: pip install -e .[llm]
"""
from __future__ import annotations

import json
import os
import re

from pydantic import BaseModel, Field

from reflecta.config import CONFIG
from reflecta.logging_config import get_logger

log = get_logger(__name__)

# Haiku 4.5: cheapest current model ($1/$5 per MTok), supports structured outputs —
# plenty for schema-constrained MCQ generation. Override via REFLECTA_ANTHROPIC_MODEL.
DEFAULT_MODEL = os.getenv("REFLECTA_ANTHROPIC_MODEL", "claude-haiku-4-5")

GENERATED_DIR = CONFIG.paths.data / "generated_banks"

_SYSTEM = """You are a psychometric item writer for a metacognitive learning platform.
You write diagnostic multiple-choice questions whose WRONG options encode specific,
common misconceptions — not random noise."""

_PROMPT_TEMPLATE = """Create a diagnostic MCQ bank for the learning goal: "{goal}".

Requirements:
1. Choose 3-5 core concepts that matter most for this goal (snake_case ids).
2. Write {n} questions total, spread across the concepts.
3. Each question: a clear stem, exactly 4 options, `correct` = 0-based index of the right one.
4. Wrong options must each encode a plausible, *specific* misconception.
5. For at least {n_twins} concepts, include a REWORDED TWIN: a second question testing the
   exact same fact with completely different phrasing. Twins share the same paraphrase_group;
   the original has is_reworded=0, the twin is_reworded=1. Twins may reorder their options.
6. difficulty: 0.2 (easy) to 0.8 (hard), your honest estimate.
7. concepts: for each concept, its importance (0-1) and target mastery (0-1) for someone
   pursuing this goal.
8. explanation: one sentence on why the correct option is right."""


# ---- structured output schema (validated by the API via messages.parse) ----
class GeneratedConcept(BaseModel):
    concept: str
    importance: float
    target: float


class GeneratedQuestion(BaseModel):
    id: str
    concept: str
    difficulty: float
    paraphrase_group: str
    is_reworded: int
    stem: str
    options: list[str]
    correct: int = Field(description="0-based index into options")
    explanation: str


class GeneratedBank(BaseModel):
    concepts: list[GeneratedConcept]
    questions: list[GeneratedQuestion]


# ---- self-verification: an independent second pass re-derives each answer ----
# This exists because of a concrete prior failure: the predecessor Kaggle project found
# ~25% of a *human-authored* MCQ dataset had wrong or ambiguous answer keys (see STORY.md).
# An LLM-generated bank is at least as capable of shipping a wrong key silently. Rather than
# trust the generation call, a second, independent call re-solves every question from just
# the stem + options (no hint of which one the generator marked correct) and any question
# where the two calls disagree is dropped before caching.
_VERIFY_SYSTEM = """You are an independent fact-checker for a multiple-choice question bank.
For each question, determine the correct option from first principles. You do not know and
must not guess what any other system marked as correct — reason from the question itself."""

_VERIFY_PROMPT_TEMPLATE = """Independently solve each of these {n} questions. For each,
return its id and the 0-based index of the option YOU believe is correct.

{items}"""


class VerifiedAnswer(BaseModel):
    id: str
    correct: int = Field(description="0-based index into that question's options, per your own reasoning")


class VerificationResult(BaseModel):
    answers: list[VerifiedAnswer]


def _verify_bank(questions: list[dict], model: str) -> list[dict]:
    """Independently re-derive each answer; drop questions where the two calls disagree.

    One batched API call for the whole bank (not one per question) to keep this cheap —
    a verification pass should not multiply the generation cost by N.
    """
    import anthropic

    items = "\n\n".join(
        f'id: {q["id"]}\nQ: {q["stem"]}\nOptions: '
        + " | ".join(f"[{i}] {opt}" for i, opt in enumerate(q["options"]))
        for q in questions
    )
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=4000,
        system=_VERIFY_SYSTEM,
        messages=[{"role": "user", "content": _VERIFY_PROMPT_TEMPLATE.format(
            n=len(questions), items=items)}],
        output_format=VerificationResult,
    )
    if response.stop_reason == "refusal":
        log.warning("verification_refused")
        return questions  # fail open: keep the original bank rather than blocking the quiz

    verdicts = {a.id: a.correct for a in response.parsed_output.answers}
    kept, dropped = [], []
    for q in questions:
        verifier_says = verdicts.get(q["id"])
        if verifier_says is None or verifier_says == q["correct"]:
            kept.append(q)
        else:
            dropped.append(q["id"])
    if dropped:
        log.warning("verification_disagreement",
                    extra={"dropped_ids": dropped, "n_dropped": len(dropped),
                          "n_total": len(questions)})
    return kept


def slugify(goal: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", goal.lower()).strip("_")[:60] or "topic"


def is_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def cached_bank_path(goal: str):
    return GENERATED_DIR / f"{slugify(goal)}.json"


def load_cached_bank(goal: str) -> dict | None:
    path = cached_bank_path(goal)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _normalize(bank: GeneratedBank) -> dict:
    """Clamp/clean the validated bank into the question-bank dict shape."""
    questions = []
    for i, q in enumerate(bank.questions):
        if len(q.options) < 3 or not (0 <= q.correct < len(q.options)):
            continue  # drop malformed items rather than failing the whole bank
        questions.append({
            "id": q.id or f"gen_q{i}",
            "concept": q.concept or "general",
            "difficulty": min(max(q.difficulty, 0.05), 0.95),
            "paraphrase_group": q.paraphrase_group or f"gen_grp{i}",
            "is_reworded": 1 if q.is_reworded else 0,
            "stem": q.stem.strip(),
            "options": q.options,
            "correct": q.correct,
            "explanation": q.explanation,
        })
    if len(questions) < 4:
        raise ValueError(f"too few valid questions after validation ({len(questions)})")
    concepts = [{"concept": c.concept,
                 "importance": min(max(c.importance, 0.0), 1.0),
                 "target": min(max(c.target, 0.1), 1.0)} for c in bank.concepts if c.concept]
    return {"concepts": concepts, "questions": questions}


def generate_bank(goal: str, n_questions: int = 14) -> dict:
    """Generate (or load cached) a topic bank for a novel goal.

    Raises RuntimeError when no API key is configured — callers turn that into a
    friendly "here's how to enable open topics" message.
    """
    cached = load_cached_bank(goal)
    if cached:
        log.info("generated_bank_cache_hit", extra={"goal": goal})
        return cached
    if not is_available():
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    import anthropic  # lazy: core installs stay light

    client = anthropic.Anthropic()
    prompt = _PROMPT_TEMPLATE.format(
        goal=goal, n=n_questions, n_twins=max(2, n_questions // 5)
    )
    log.info("generating_bank", extra={"goal": goal, "model": DEFAULT_MODEL})
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=16000,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=GeneratedBank,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model declined to generate this topic")
    bank = _normalize(response.parsed_output)

    n_before = len(bank["questions"])
    verified = _verify_bank(bank["questions"], model=DEFAULT_MODEL)
    if len(verified) < 4:
        raise ValueError(
            f"only {len(verified)}/{n_before} questions survived independent verification"
        )
    bank["questions"] = verified
    bank["meta"] = {
        "goal": goal, "model": DEFAULT_MODEL, "generated": True,
        "verification": {"n_generated": n_before, "n_verified": len(verified),
                         "n_dropped": n_before - len(verified)},
    }

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    cached_bank_path(goal).write_text(json.dumps(bank, indent=2), encoding="utf-8")
    log.info("generated_bank_saved",
             extra={"goal": goal, "n_questions": len(bank["questions"]),
                   "n_dropped": n_before - len(verified)})
    return bank
