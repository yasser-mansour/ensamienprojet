"""
Load an experience definition (fixtures/*.json) into the content tables.

The loader is idempotent: it upserts by experience slug, mission order and
question order, so it can be re-run after editing the JSON. It is used both by
the `seed_energy_lab` management command and by a data migration (with
historical models), so it only uses plain ORM calls.
"""

import json
import string
from pathlib import Path

from django.conf import settings

DEFAULT_FIXTURE = Path(settings.BASE_DIR) / "fixtures" / "energy_lab.json"
OPTION_KEYS = string.ascii_uppercase


class ContentError(ValueError):
    pass


def _validate_question(q, option_keys, where):
    kind, key = q["kind"], q["answer_key"]
    if kind in ("SINGLE", "TRUE_FALSE"):
        if key not in option_keys:
            raise ContentError(f"{where}: answer {key!r} is not an option")
    elif kind == "MATCH":
        item_keys = {item["key"] for item in q.get("items", [])}
        if set(key) != item_keys or not set(key.values()) <= set(option_keys):
            raise ContentError(f"{where}: invalid matching key")
    elif kind == "ORDER":
        if sorted(key) != sorted(option_keys):
            raise ContentError(f"{where}: order must be a permutation of the cards")
    else:
        raise ContentError(f"{where}: unknown kind {kind!r}")


def load_experience(Experience, Mission, Question, AnswerOption, path=DEFAULT_FIXTURE):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    exp_data = data["experience"]
    experience, _ = Experience.objects.update_or_create(
        slug=exp_data["slug"],
        defaults={k: exp_data.get(k, "") for k in ("title", "subtitle", "source_reference")},
    )
    counts = {"missions": 0, "questions": 0}
    for m in data["missions"]:
        mission, _ = Mission.objects.update_or_create(
            experience=experience,
            order=m["order"],
            defaults={
                "code": m["code"],
                "slug": m["slug"],
                "title": m["title"],
                "objective": m["objective"],
                "briefing": m.get("briefing", ""),
                "default_duration": m["default_duration"],
                "is_final": m.get("is_final", False),
            },
        )
        counts["missions"] += 1
        for index, q in enumerate(m["questions"], start=1):
            option_keys = list(OPTION_KEYS[: len(q["options"])])
            _validate_question(q, option_keys, f"mission {m['code']} question {index}")
            question, _ = Question.objects.update_or_create(
                mission=mission,
                order=index,
                defaults={
                    "kind": q["kind"],
                    "label": q.get("label", ""),
                    "prompt": q["prompt"],
                    "context": q.get("context", ""),
                    "items": q.get("items", []),
                    "answer_key": q["answer_key"],
                    "answer_display": q["answer_display"],
                    "explanation": q["explanation"],
                    "clarification": q.get("clarification", ""),
                    "source": q["source"],
                    "source_reference": q["source_reference"],
                    "points": q.get("points", 100),
                    "duration": q.get("duration"),
                },
            )
            AnswerOption.objects.filter(question=question).delete()
            AnswerOption.objects.bulk_create(
                AnswerOption(question=question, key=key, text=text, order=i)
                for i, (key, text) in enumerate(zip(option_keys, q["options"]))
            )
            counts["questions"] += 1
    return experience, counts


def load_default():
    from .models import AnswerOption, Experience, Mission, Question

    return load_experience(Experience, Mission, Question, AnswerOption)
