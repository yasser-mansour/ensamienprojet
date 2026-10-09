from django.test import TestCase

from games.content import load_default
from games.models import Mission, Question
from live.grading import is_correct, normalize_answer


class MissionContentTests(TestCase):
    def test_five_missions_in_order_with_expected_sizes(self):
        missions = list(Mission.objects.order_by("order"))
        self.assertEqual(
            [(m.code, m.title, m.questions.count(), m.default_duration) for m in missions],
            [
                ("01", "ENERGY SCAN", 5, 20),
                ("02", "VOCABULARY BATTLE", 8, 25),
                ("03", "CRASH DETECTIVE", 7, 35),
                ("04", "ERROR 404: ENGINEER ENGLISH", 5, 30),
                ("05", "FINAL CRASH SIMULATION", 1, 60),
            ],
        )

    def test_every_question_has_valid_key_explanation_and_source(self):
        for q in Question.objects.prefetch_related("options"):
            keys = [o.key for o in q.options.all()]
            self.assertTrue(q.explanation and q.source_reference and q.answer_display, q)
            self.assertIn(q.source, ("TEXTBOOK", "SUPPLEMENTARY"))
            if q.kind in ("SINGLE", "TRUE_FALSE"):
                self.assertIn(q.answer_key, keys)
            answer = {"MATCH": {"pairs": q.answer_key}, "ORDER": {"order": q.answer_key}}.get(q.kind, {"option": q.answer_key})
            self.assertTrue(is_correct(q, normalize_answer(q, keys, answer)), q)

    def test_final_boss_sequence_and_points(self):
        q = Question.objects.get(mission__code="05")
        cards = {o.key: o.text for o in q.options.all()}
        self.assertEqual(
            [cards[k] for k in q.answer_key],
            ["SEATBELT STRETCHES", "STOPPING DISTANCE INCREASES", "FORCE ON PASSENGER DECREASES", "INJURIES DECREASE"],
        )
        self.assertEqual(q.points, 300)

    def test_crash_detective_textbook_answers(self):
        answers = list(Question.objects.filter(mission__code="03").order_by("order").values_list("answer_display", flat=True))
        self.assertEqual(answers, ["FALSE", "FALSE", "TRUE", "TRUE", "FALSE", "FALSE", "TRUE"])
        first = Question.objects.get(mission__code="03", order=1)
        self.assertIn("potential energy to become kinetic energy", first.explanation)  # textbook wording preserved
        self.assertTrue(first.clarification.startswith("Science note"))  # separate supplementary note

    def test_task4_matching_key(self):
        q = Question.objects.get(kind="MATCH")
        self.assertEqual(q.answer_key, {"1": "A", "2": "D", "3": "C", "4": "B"})

    def test_reload_is_idempotent(self):
        load_default()
        load_default()
        self.assertEqual(Mission.objects.count(), 5)
        self.assertEqual(Question.objects.count(), 26)
