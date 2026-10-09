"""
Server-side answer validation and grading. Clients only send *what they chose*;
correctness and points are always computed here.

Answer formats:
    SINGLE / TRUE_FALSE  {"option": "B"}
    MATCH                {"pairs": {"1": "A", "2": "D", ...}}   (every item must be paired)
    ORDER                {"order": ["B", "D", "A", "C"]}          (a permutation of all cards)
"""

from games.models import Question


class AnswerFormatError(ValueError):
    pass


def normalize_answer(question, option_keys, answer):
    if not isinstance(answer, dict):
        raise AnswerFormatError("Answer must be an object.")
    kind = question.kind
    if kind in (Question.Kind.SINGLE, Question.Kind.TRUE_FALSE):
        option = answer.get("option")
        if not isinstance(option, str) or option not in option_keys:
            raise AnswerFormatError("Choose one of the available answers.")
        return {"option": option}
    if kind == Question.Kind.MATCH:
        pairs = answer.get("pairs")
        item_keys = {item["key"] for item in question.items}
        if not isinstance(pairs, dict) or set(pairs) != item_keys:
            raise AnswerFormatError("Match every word before submitting.")
        if not all(isinstance(v, str) and v in option_keys for v in pairs.values()):
            raise AnswerFormatError("Invalid definition selected.")
        return {"pairs": {k: pairs[k] for k in sorted(pairs)}}
    if kind == Question.Kind.ORDER:
        order = answer.get("order")
        if not isinstance(order, list) or sorted(order) != sorted(option_keys) or len(set(order)) != len(order):
            raise AnswerFormatError("Place every card exactly once.")
        return {"order": list(order)}
    raise AnswerFormatError("Unsupported question type.")


def is_correct(question, normalized):
    key = question.answer_key
    if question.kind in (Question.Kind.SINGLE, Question.Kind.TRUE_FALSE):
        return normalized["option"] == key
    if question.kind == Question.Kind.MATCH:
        return normalized["pairs"] == {k: key[k] for k in sorted(key)}
    if question.kind == Question.Kind.ORDER:
        return normalized["order"] == list(key)
    return False


def describe_answer(question, normalized, option_text):
    """Human-readable rendering of a stored answer (history pages)."""
    if not normalized:
        return "—"
    if "option" in normalized:
        return f"{normalized['option']} · {option_text.get(normalized['option'], '')}"
    if "pairs" in normalized:
        return " · ".join(f"{k}→{v}" for k, v in normalized["pairs"].items())
    if "order" in normalized:
        return " → ".join(normalized["order"])
    return str(normalized)
