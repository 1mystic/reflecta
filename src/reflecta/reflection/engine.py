"""Reflection engine — turn signals into specific, realistic prompts (signal #5).

Free-only by design. Two modes:
  - "rules"  : deterministic templates over the signal bundle. No model, always available,
               fully explainable. This is the default and the fallback.
  - "llm"    : a local/open model (Ollama or transformers) rephrases the rule-derived
               facts into a warmer, personalized reflection. Never invents facts — it is
               given the exact numbers and told to explain, not assess.

The rules mode is intentionally strong on its own: the value is the *diagnosis*, and the
diagnosis comes from the signals, not from an LLM's opinion.
"""
from __future__ import annotations

from reflecta.config import CONFIG
from reflecta.models.intent_gap import GapReport


def _rules_reflection(signals: dict, gap: GapReport | None) -> list[str]:
    out: list[str] = []

    tp = signals.get("timing_profile") or {}
    if tp.get("fast_wrong", 0) > 0.2:
        out.append(
            "You answer a lot of questions quickly and get them wrong — that pattern usually "
            "means a confident misconception, not carelessness. Slow down on those topics and "
            "check *why* your first instinct is off."
        )
    if tp.get("slow_correct", 0) > 0.4:
        out.append(
            "You're getting things right, but effortfully. That's real learning in progress — "
            "with spaced repetition these should become fast-correct (fluent)."
        )

    mi = signals.get("memorization_index")
    if mi is not None and mi == mi and mi > 0.15:  # not NaN and meaningful
        out.append(
            f"When the same idea is reworded, your accuracy drops by {mi:.0%}. You're "
            "recognizing familiar phrasing more than understanding the concept — try "
            "explaining it in your own words before answering."
        )

    # calibration: direction-aware (over- vs under-confidence), mirrors the metric tile
    cal = signals.get("calibration") or {}
    ece, direction = cal.get("ece"), cal.get("direction")
    if ece is not None and ece > 0.15 and direction is not None:
        if direction > 0.1:
            out.append(
                f"Your confidence runs well above your accuracy (calibration error {ece:.2f}). "
                "Overconfidence hides gaps — before answering, ask what would make you wrong."
            )
        elif direction < -0.1:
            out.append(
                f"You're more capable than you think — your answers beat your confidence by a wide "
                f"margin (calibration error {ece:.2f}). Trust your reasoning more."
            )
        else:
            out.append(
                f"Your confidence and accuracy are noticeably out of sync (calibration error "
                f"{ece:.2f}) — rate yourself more deliberately on each question."
            )

    if gap is not None:
        out.append(
            f"Toward your goal ('{gap.goal}') you're about {gap.readiness:.0%} ready."
        )
        top = gap.top_gaps[:2]
        if top:
            names = ", ".join(g.concept.replace('_', ' ') for g in top if g.gap > 0)
            if names:
                out.append(f"The highest-leverage gap right now is: {names}. "
                           "Focus study time here — it moves your goal the most.")
        if gap.misallocation:
            names = ", ".join(c.replace('_', ' ') for c in gap.misallocation)
            out.append(f"You're spending real effort on {names}, which your goal barely "
                       "needs. Consider redirecting that time.")

    if not out:
        out.append("Not enough signal yet — take a few more questions and I'll reflect back "
                   "specific patterns.")
    return out


def generate_reflection(signals: dict, gap: GapReport | None = None, mode: str | None = None):
    """Return a list of reflection statements. `mode`: 'rules' (default) or 'llm'."""
    facts = _rules_reflection(signals, gap)
    mode = mode or ("llm" if CONFIG.llm_backend != "none" else "rules")
    if mode != "llm":
        return facts

    prompt = (
        "You are a supportive learning coach. Rephrase the following factual observations "
        "into a short, warm reflection for the learner. Do NOT add new claims or numbers; "
        "only rephrase what is given.\n\nObservations:\n- " + "\n- ".join(facts)
    )
    try:
        return [_call_local_llm(prompt)]
    except Exception as e:
        print(f"[reflection] LLM backend failed ({e}); returning rule-based facts.")
        return facts


def _call_local_llm(prompt: str) -> str:
    """Call a free/local OpenAI-compatible endpoint (e.g. Ollama). No paid API."""
    import requests

    resp = requests.post(
        f"{CONFIG.llm_base_url}/chat/completions",
        json={
            "model": CONFIG.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()
