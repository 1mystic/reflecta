"""Question bank — serve quiz items with answers hidden, then grade submissions.

The bank JSON lives at data/question_bank.json. `correct` is a 0-based index that is
NEVER serialized to the client; the server keeps an answer key per session and grades
against it. Options are shuffled per delivery so there's no positional shortcut.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field

from reflecta.config import CONFIG

BANK_PATH = CONFIG.paths.data / "question_bank.json"
_LETTERS = ["A", "B", "C", "D", "E"]


@dataclass
class ServedQuestion:
    """What the client sees — no correct answer."""
    id: str
    concept: str
    stem: str
    options: dict[str, str]  # letter -> text (already shuffled)
    is_reworded: int


@dataclass
class _KeyEntry:
    """Server-side answer key for one served question."""
    id: str
    concept: str
    difficulty: float
    paraphrase_group: str
    is_reworded: int
    correct_letter: str
    explanation: str


@dataclass
class QuizDelivery:
    questions: list[ServedQuestion]
    key: dict[str, _KeyEntry] = field(default_factory=dict)  # question id -> key


class QuestionBank:
    def __init__(self, path=BANK_PATH):
        with open(path, encoding="utf-8") as f:
            self._raw = json.load(f)["questions"]
        self._by_id = {q["id"]: q for q in self._raw}

    @classmethod
    def from_dict(cls, bank: dict) -> "QuestionBank":
        """Build a bank from an in-memory dict (e.g. a Claude-generated topic bank)."""
        obj = cls.__new__(cls)
        obj._raw = bank["questions"]
        obj._by_id = {q["id"]: q for q in obj._raw}
        return obj

    def concepts(self) -> set[str]:
        return {q["concept"] for q in self._raw}

    def item_difficulties(self) -> dict[str, float]:
        """Bank-authored difficulty per concept (mean) — used for online mastery."""
        by_concept: dict[str, list[float]] = {}
        for q in self._raw:
            by_concept.setdefault(q["concept"], []).append(q["difficulty"])
        return {c: sum(v) / len(v) for c, v in by_concept.items()}

    def sample(self, n: int = 12, concepts: set[str] | None = None,
               seed: int | None = None) -> QuizDelivery:
        """Pick up to n questions, keeping reworded twins together, and shuffle options.

        Keeping paraphrase pairs together is what makes the memorization signal usable:
        the learner sees both the original and the reworded probe of the same concept.
        """
        rng = random.Random(seed)
        pool = [q for q in self._raw if concepts is None or q["concept"] in concepts]

        # group by paraphrase_group so twins travel together
        groups: dict[str, list[dict]] = {}
        for q in pool:
            groups.setdefault(q["paraphrase_group"], []).append(q)
        order = list(groups.values())
        rng.shuffle(order)

        chosen: list[dict] = []
        for grp in order:
            if len(chosen) >= n:
                break
            chosen.extend(grp)
        chosen = chosen[:n]

        served, key = [], {}
        for q in chosen:
            served_q, entry = self._serve_one(q, rng)
            served.append(served_q)
            key[q["id"]] = entry
        return QuizDelivery(questions=served, key=key)

    def _serve_one(self, q: dict, rng: random.Random) -> tuple[ServedQuestion, _KeyEntry]:
        idxs = list(range(len(q["options"])))
        rng.shuffle(idxs)
        letters = _LETTERS[: len(idxs)]
        options = {letters[i]: q["options"][idxs[i]] for i in range(len(idxs))}
        correct_letter = letters[idxs.index(q["correct"])]
        served = ServedQuestion(
            id=q["id"], concept=q["concept"], stem=q["stem"],
            options=options, is_reworded=q["is_reworded"],
        )
        entry = _KeyEntry(
            id=q["id"], concept=q["concept"], difficulty=q["difficulty"],
            paraphrase_group=q["paraphrase_group"], is_reworded=q["is_reworded"],
            correct_letter=correct_letter, explanation=q["explanation"],
        )
        return served, entry

    @staticmethod
    def grade(answer: dict, key: _KeyEntry) -> dict:
        """Turn one raw answer + its key into a canonical interaction row.

        answer: {question_id, chosen_letter, response_time, confidence}
        """
        correct = int(answer.get("chosen_letter") == key.correct_letter)
        return {
            "item_id": key.id,
            "skill": key.concept,
            "correct": correct,
            "difficulty": key.difficulty,
            "response_time": answer.get("response_time"),
            "chosen_option": answer.get("chosen_letter"),
            "confidence": answer.get("confidence"),
            "paraphrase_group": key.paraphrase_group,
            "is_reworded": key.is_reworded,
            "correct_letter": key.correct_letter,
            "explanation": key.explanation,
        }
