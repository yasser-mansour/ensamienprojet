import json
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from live import services
from live.models import GameSession, QuestionRuntime, ScoreEvent, TeamSubmission

from .helpers import act, correct_answer, current_question, join, make_host, new_session, refresh, scores, submit, team_client, wrong_answer


class SubmissionTests(TestCase):
    def setUp(self):
        self.host = make_host()
        self.session = new_session(self.host)
        self.team, token = join(self.session, "Vector")
        self.client_team = team_client(token)
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        self.question = current_question(self.session)

    def test_answer_accepted_and_acknowledged(self):
        response = submit(self.client_team, self.session, correct_answer(self.question))
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["accepted"])
        self.assertFalse(body["duplicate"])
        self.assertFalse({"correct", "is_correct", "points"} & set(body))  # correctness stays hidden until reveal
        self.assertEqual(TeamSubmission.objects.count(), 1)

    def test_identical_retry_is_idempotent(self):
        submit(self.client_team, self.session, correct_answer(self.question))
        retry = submit(self.client_team, self.session, correct_answer(self.question))
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.json()["duplicate"])
        self.assertEqual(TeamSubmission.objects.count(), 1)

    def test_changing_answer_after_submission_rejected(self):
        submit(self.client_team, self.session, wrong_answer(self.question))
        second = submit(self.client_team, self.session, correct_answer(self.question))
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["error"]["code"], "ALREADY_ANSWERED")
        self.assertFalse(TeamSubmission.objects.get().is_correct)

    def test_late_answer_rejected_by_server_clock(self):
        QuestionRuntime.objects.update(deadline=timezone.now() - timedelta(seconds=2))
        response = submit(self.client_team, self.session, correct_answer(self.question))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "TIME_UP")

    def test_answer_within_grace_period_accepted(self):
        QuestionRuntime.objects.update(deadline=timezone.now() - timedelta(seconds=0.5))
        self.assertEqual(submit(self.client_team, self.session, correct_answer(self.question)).status_code, 201)

    def test_closed_question_rejects_answers(self):
        act(self.session, self.host, "close_question")
        response = submit(self.client_team, self.session, correct_answer(self.question))
        self.assertEqual(response.json()["error"]["code"], "QUESTION_CLOSED")

    def test_stale_runtime_rejected(self):
        response = self.client_team.post(
            "/api/live/submit/", data=json.dumps({"runtime_id": 999999, "answer": {"option": "A"}}), content_type="application/json"
        )
        self.assertEqual(response.json()["error"]["code"], "STALE_QUESTION")

    def test_invalid_answer_formats_rejected(self):
        for answer in [None, "A", {"option": "Z"}, {"option": ["A"]}, {"order": ["A"]}, {}]:
            response = submit(self.client_team, self.session, answer)
            self.assertEqual(response.status_code, 400, answer)
        self.assertEqual(TeamSubmission.objects.count(), 0)

    def test_client_cannot_send_score_or_correctness(self):
        session = refresh(self.session)
        response = self.client_team.post(
            "/api/live/submit/",
            data=json.dumps(
                {"runtime_id": session.current_runtime_id, "answer": wrong_answer(self.question), "correct": True, "points": 1000}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        act(self.session, self.host, "close_question")
        act(self.session, self.host, "reveal_answer")
        self.assertEqual(scores(self.session)["Vector"], 0)

    def test_submit_requires_team_credential_and_csrf(self):
        from django.test import Client

        self.assertEqual(submit(Client(), self.session, correct_answer(self.question)).status_code, 401)
        strict = Client(enforce_csrf_checks=True)
        strict.cookies["ensamien_team"] = self.client_team.cookies["ensamien_team"].value
        self.assertEqual(submit(strict, self.session, correct_answer(self.question)).status_code, 403)

    def test_removed_team_cannot_submit(self):
        act(self.session, self.host, "remove_team", {"team_id": self.team.pk})
        response = submit(self.client_team, self.session, correct_answer(self.question))
        self.assertEqual(response.json()["error"]["code"], "TEAM_REMOVED")


class ScoringTests(TestCase):
    def setUp(self):
        self.host = make_host()
        self.session = new_session(self.host)
        self.clients = {}
        for name in ["Apollo", "Nova", "Titan"]:
            team, token = join(self.session, name)
            self.clients[name] = (team, team_client(token))
        act(self.session, self.host, "start_game")

    def play(self, answers):
        """answers: {team: 'right'|'wrong'|None}; plays the current question through reveal."""
        if refresh(self.session).status == "MISSION_INTRO":
            act(self.session, self.host, "start_question")
        q = current_question(self.session)
        for name, kind in answers.items():
            if kind:
                answer = correct_answer(q) if kind == "right" else wrong_answer(q)
                self.assertEqual(submit(self.clients[name][1], self.session, answer).status_code, 201)
        act(self.session, self.host, "close_question")
        act(self.session, self.host, "reveal_answer")
        return q

    def test_correct_scores_100_incorrect_and_missing_score_0(self):
        self.play({"Apollo": "right", "Nova": "wrong", "Titan": None})
        self.assertEqual(scores(self.session), {"Apollo": 100, "Nova": 0, "Titan": 0})

    def test_scores_only_awarded_at_reveal(self):
        act(self.session, self.host, "start_question")
        q = current_question(self.session)
        submit(self.clients["Apollo"][1], self.session, correct_answer(q))
        act(self.session, self.host, "close_question")
        self.assertEqual(scores(self.session)["Apollo"], 0)
        act(self.session, self.host, "reveal_answer")
        self.assertEqual(scores(self.session)["Apollo"], 100)

    def test_matching_and_final_boss_scoring(self):
        for _ in range(4):
            act(self.session, self.host, "next_mission")
        # Mission 05 — Final Crash Simulation (300 EP, sequence)
        q = self.play({"Apollo": "right", "Nova": "wrong"})
        self.assertEqual(q.kind, "ORDER")
        self.assertEqual(q.answer_key, ["B", "D", "A", "C"])
        self.assertEqual(scores(self.session), {"Apollo": 300, "Nova": 0, "Titan": 0})

    def test_matching_question_all_or_nothing(self):
        act(self.session, self.host, "next_mission")
        act(self.session, self.host, "start_question")
        for _ in range(5):  # advance to Mission 02 question 6 (matching)
            act(self.session, self.host, "close_question")
            act(self.session, self.host, "reveal_answer")
            act(self.session, self.host, "next_question")
        q = current_question(self.session)
        self.assertEqual(q.kind, "MATCH")
        nearly = correct_answer(q)
        nearly["pairs"]["1"], nearly["pairs"]["2"] = nearly["pairs"]["2"], nearly["pairs"]["1"]
        submit(self.clients["Apollo"][1], self.session, correct_answer(q))
        submit(self.clients["Nova"][1], self.session, nearly)
        incomplete = {"pairs": {"1": "A"}}
        self.assertEqual(submit(self.clients["Titan"][1], self.session, incomplete).status_code, 400)
        act(self.session, self.host, "close_question")
        act(self.session, self.host, "reveal_answer")
        self.assertEqual(scores(self.session), {"Apollo": 100, "Nova": 0, "Titan": 0})

    def test_reveal_twice_is_impossible(self):
        self.play({"Apollo": "right"})
        from live import engine

        with self.assertRaises(engine.ActionError):
            act(self.session, self.host, "reveal_answer")
        # Even calling the award routine again cannot double-score.
        services.award_runtime(refresh(self.session), refresh(self.session).current_runtime)
        self.assertEqual(scores(self.session)["Apollo"], 100)

    def test_manual_adjustments_are_recorded(self):
        apollo = self.clients["Apollo"][0]
        act(self.session, self.host, "adjust_score", {"team_id": apollo.pk, "points": 50, "reason": "Speaking participation"})
        act(self.session, self.host, "adjust_score", {"team_id": apollo.pk, "points": -20, "reason": "Scoring correction"})
        self.assertEqual(scores(self.session)["Apollo"], 30)
        events = list(ScoreEvent.objects.filter(source="MANUAL").order_by("created_at"))
        self.assertEqual([(e.points, e.reason, e.created_by) for e in events], [(50, "Speaking participation", self.host), (-20, "Scoring correction", self.host)])
        from live import engine

        for params in ({"team_id": apollo.pk, "points": 0, "reason": "x"}, {"team_id": apollo.pk, "points": 10, "reason": ""}, {"team_id": 0, "points": 10, "reason": "x"}):
            with self.assertRaises(engine.ActionError):
                act(self.session, self.host, "adjust_score", params)

    def test_leaderboard_ordering_and_ties(self):
        self.play({"Apollo": "right", "Nova": "right", "Titan": "wrong"})
        act(self.session, self.host, "next_question")
        self.play({"Apollo": "wrong", "Nova": "right", "Titan": "right"})
        board = services.leaderboard(refresh(self.session))
        self.assertEqual([(r["name"], r["score"], r["rank"]) for r in board], [("Nova", 200, 1), ("Apollo", 100, 2), ("Titan", 100, 2)])

    def test_removed_team_excluded_from_leaderboard_but_history_kept(self):
        self.play({"Apollo": "right", "Nova": "right"})
        act(self.session, self.host, "remove_team", {"team_id": self.clients["Nova"][0].pk})
        self.assertNotIn("Nova", scores(self.session))
        self.assertEqual(ScoreEvent.objects.filter(team=self.clients["Nova"][0]).count(), 1)

    def test_speed_bonus_disabled_by_default_and_configurable(self):
        self.assertFalse(refresh(self.session).speed_bonus_enabled)
        act(self.session, self.host, "toggle_speed_bonus")
        self.play({"Apollo": "right"})
        apollo = scores(self.session)["Apollo"]
        self.assertGreater(apollo, 100)
        self.assertLessEqual(apollo, 150)


class ConcurrentScoringIntegrity(TestCase):
    def test_question_award_unique_constraint(self):
        from django.db import IntegrityError, transaction

        host = make_host()
        session = new_session(host)
        team, _ = join(session, "A")
        act(session, host, "start_game")
        act(session, host, "start_question")
        q = current_question(session)
        ScoreEvent.objects.create(session=session, team=team, points=100, reason="x", source="QUESTION", question=q)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ScoreEvent.objects.create(session=session, team=team, points=100, reason="x", source="QUESTION", question=q)
        self.assertEqual(GameSession.objects.count(), 1)
