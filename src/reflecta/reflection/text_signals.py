"""Reflection text signals - extract metacognitive signals from a learner's own words.

Feature C of the Cognitive Vitals work: after a quiz, the learner can write one line about
why they chose what they chose. We run that through Claude (Haiku) with a constrained schema
to surface signals the behavioral metrics can't see - stated confidence, hedging language,
and named misconceptions - and feed them into the reflection.

This mirrors generation.py exactly: guarded by generation.is_available() so it degrades
gracefully with no ANTHROPIC_API_KEY (returns None, feature simply hides), lazy `import
anthropic`, structured output via `client.messages.parse(output_format=...)`, and a refusal
check. Nothing here is required for the app to run - it is purely additive.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from reflecta import generation
from reflecta.logging_config import get_logger

log = get_logger(__name__)

_SYSTEM = """You analyze a learner's short free-text reflection about a quiz they just took.
Extract only what the text actually supports - do not invent. Return:
- confidence: 0..1, how sure the learner sounds about their own understanding (hedged,
  uncertain language -> low; assertive, specific language -> high).
- hedging: true if the text leans on qualifiers ("I think", "maybe", "not sure", "guessed").
- misconception_flags: short phrases naming any specific wrong belief the learner reveals
  (empty list if none is stated - do not speculate).
- summary: one plain sentence, second person ("You ..."), describing their metacognitive
  state. No preamble. Plain hyphens only, never em dashes."""


class ReflectionSignals(BaseModel):
    confidence: float = Field(ge=0.0, le=1.0)
    hedging: bool
    misconception_flags: list[str] = Field(default_factory=list)
    summary: str


def extract_reflection_signals(text: str | None) -> ReflectionSignals | None:
    """Extract signals from a learner reflection, or None if unavailable.

    Returns None (feature off) when the text is empty/whitespace, when ANTHROPIC_API_KEY is
    not configured, or on any model/parse failure - the caller treats None as "no signals"
    and hides the section, so prod without a key behaves exactly like generate_bank."""
    if not text or not text.strip():
        return None
    if not generation.is_available():
        return None

    try:
        import anthropic  # lazy: core installs stay light

        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=generation.DEFAULT_MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{"role": "user", "content": text.strip()[:1000]}],
            output_format=ReflectionSignals,
        )
        if response.stop_reason == "refusal":
            return None
        return response.parsed_output
    except Exception:
        log.exception("reflection_signal_extraction_failed")
        return None
