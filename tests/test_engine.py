import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from live import engine
from live.models import GameSession, QuestionRuntime, ScoreEvent

from .helpers import (
    act,
    correct_answer,
    current_question,
    host_client,
    join,
    make_host,
    new_session,
    refresh,
    scores,
    submit,
    team_client,
    wrong_answer,
)


class StateMachineTests(TestCase):
    def setUp(self):
        self.host = make_host()
        self.session = new_session(self.host)
        self.team, self.token = join(self.session, "Vector")
        self.client_team = team_client(self.token)

    def status(self):
        return refresh(self.session).status

    def test_start_game_requires_a_team(self):
        empty = new_session(self.host)
        with self.assertRaises(engine.ActionError) as ctx:
            act(empty, self.host, "start_game")
        self.assertEqual(ctx.exception.code, "NO_TEAMS")
        self.assertNotIn("start_game", engine.allowed_actions(empty))

    def test_start_game_closes_registration_and_enters_mission_one(self):
        act(self.session, self.host, "start_game")
        s = refresh(self.session)
        self.assertEqual(s.status, "MISSION_INTRO")
        self.assertFalse(s.registration_open)
        self.assertEqual(s.current_mission.code, "01")
        self.assertIsNotNone(s.started_at)

    def test_main_path_through_one_question(self):
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        self.assertEqual(self.status(), "QUESTION_OPEN")
        rt = refresh(self.session).current_runtime
        self.assertEqual(rt.status, "OPEN")
        self.assertAlmostEqual((rt.deadline - rt.opened_at).total_seconds(), 20, delta=0.01)  # Energy Scan default
        act(self.session, self.host, "close_question")
        self.assertEqual(self.status(), "QUESTION_CLOSED")
        act(self.session, self.host, "reveal_answer")
        self.assertEqual(self.status(), "ANSWER_REVEALED")
        act(self.session, self.host, "show_leaderboard")
        self.assertEqual(self.status(), "LEADERBOARD")
        act(self.session, self.host, "next_question")
        self.assertEqual(self.status(), "QUESTION_OPEN")
        self.assertEqual(current_question(self.session).order, 2)

    def test_timer_reaching_zero_does_not_reveal(self):
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        QuestionRuntime.objects.update(deadline=timezone.now() - timedelta(seconds=30))
        self.client_team.get("/api/live/state/")
        self.assertEqual(self.status(), "QUESTION_OPEN")
        state = self.client_team.get("/api/live/state/").json()["state"]
        self.assertNotIn("reveal", state)

    def test_invalid_transitions_are_rejected_with_message(self):
        with self.assertRaises(engine.ActionError) as ctx:
            act(self.session, self.host, "reveal_answer")
        self.assertEqual(ctx.exception.code, "INVALID_TRANSITION")
        self.assertIn("Cannot reveal the answer while the session is LOBBY", ctx.exception.message)
        act(self.session, self.host, "start_game")
        for action in ("start_game", "close_question", "reveal_answer", "next_question", "resume", "archive"):
            with self.assertRaises(engine.ActionError, msg=action):
                act(self.session, self.host, action)
        act(self.session, self.host, "start_question")
        with self.assertRaises(engine.ActionError):
            act(self.session, self.host, "reveal_answer")  # must close first

    def test_stale_click_does_not_advance_twice(self):
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        s = refresh(self.session)
        engine.perform(s.pk, self.host, "close_question", expected_status="QUESTION_OPEN", expected_runtime=s.current_runtime_id)
        with self.assertRaises(engine.ActionError) as ctx:
            engine.perform(s.pk, self.host, "close_question", expected_status="QUESTION_OPEN", expected_runtime=s.current_runtime_id)
        self.assertEqual(ctx.exception.code, "STALE")
        # Two dashboards clicking "next" from the same reveal advance only once.
        engine.perform(s.pk, self.host, "reveal_answer", expected_status="QUESTION_CLOSED", expected_runtime=s.current_runtime_id)
        engine.perform(s.pk, self.host, "next_question", expected_status="ANSWER_REVEALED", expected_runtime=s.current_runtime_id)
        with self.assertRaises(engine.ActionError):
            engine.perform(s.pk, self.host, "next_question", expected_status="ANSWER_REVEALED", expected_runtime=s.current_runtime_id)
        self.assertEqual(current_question(self.session).order, 2)

    def test_retried_request_id_is_applied_once(self):
        first = act(self.session, self.host, "adjust_score", {"team_id": self.team.pk, "points": 50, "reason": "Teamwork"}, request_id="abc")
        second = act(self.session, self.host, "adjust_score", {"team_id": self.team.pk, "points": 50, "reason": "Teamwork"}, request_id="abc")
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(scores(self.session)["Vector"], 50)

    def test_guarded_actions_require_expected_state(self):
        with self.assertRaises(engine.ActionError) as ctx:
            engine.perform(self.session.pk, self.host, "start_game")
        self.assertEqual(ctx.exception.code, "MISSING_STATE")

    def test_pause_freezes_and_resume_restores_timer(self):
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        rt = refresh(self.session).current_runtime
        QuestionRuntime.objects.filter(pk=rt.pk).update(deadline=timezone.now() + timedelta(seconds=12))
        act(self.session, self.host, "pause")
        s = refresh(self.session)
        self.assertEqual((s.status, s.paused_from), ("PAUSED", "QUESTION_OPEN"))
        rt.refresh_from_db()
        self.assertIsNone(rt.deadline)
        self.assertAlmostEqual(rt.paused_remaining_ms, 12000, delta=300)
        # Submissions are refused while paused.
        response = submit(self.client_team, self.session, correct_answer(rt.question))
        self.assertEqual(response.json()["error"]["code"], "PAUSED")
        act(self.session, self.host, "resume")
        s = refresh(self.session)
        self.assertEqual((s.status, s.paused_from), ("QUESTION_OPEN", ""))
        rt.refresh_from_db()
        self.assertAlmostEqual((rt.deadline - timezone.now()).total_seconds(), 12, delta=0.5)
        self.assertEqual(submit(self.client_team, self.session, correct_answer(rt.question)).status_code, 201)

    def test_pause_resume_from_lobby_and_reveal(self):
        act(self.session, self.host, "pause")
        act(self.session, self.host, "resume")
        self.assertEqual(self.status(), "LOBBY")
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        act(self.session, self.host, "close_question")
        act(self.session, self.host, "reveal_answer")
        act(self.session, self.host, "pause")
        act(self.session, self.host, "resume")
        self.assertEqual(self.status(), "ANSWER_REVEALED")

    def test_extend_time(self):
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        before = refresh(self.session).current_runtime.deadline
        act(self.session, self.host, "extend_time", {"seconds": 15})
        after = refresh(self.session).current_runtime.deadline
        self.assertAlmostEqual((after - before).total_seconds(), 15, delta=0.01)
        with self.assertRaises(engine.ActionError):
            act(self.session, self.host, "extend_time", {"seconds": 9999})

    def test_reopen_closed_question_keeps_existing_answers(self):
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        q = current_question(self.session)
        submit(self.client_team, self.session, correct_answer(q))
        act(self.session, self.host, "close_question")
        act(self.session, self.host, "reopen_question", {"seconds": 10})
        s = refresh(self.session)
        self.assertEqual(s.status, "QUESTION_OPEN")
        self.assertEqual(s.current_runtime.submissions.count(), 1)

    def test_skip_question_awards_nothing_and_advances(self):
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        q = current_question(self.session)
        rt_id = refresh(self.session).current_runtime_id
        submit(self.client_team, self.session, correct_answer(q))
        act(self.session, self.host, "skip_question")
        self.assertEqual(QuestionRuntime.objects.get(pk=rt_id).status, "SKIPPED")
        self.assertEqual(current_question(self.session).order, 2)
        self.assertEqual(scores(self.session)["Vector"], 0)

    def test_mission_progression_and_final_mission(self):
        act(self.session, self.host, "start_game")
        codes = []
        while True:
            s = refresh(self.session)
            codes.append(s.current_mission.code)
            act(self.session, self.host, "start_question")
            while refresh(self.session).status != "MISSION_COMPLETE":
                act(self.session, self.host, "close_question")
                act(self.session, self.host, "reveal_answer")
                act(self.session, self.host, "next_question")
            if "next_mission" not in engine.allowed_actions(refresh(self.session)):
                break
            act(self.session, self.host, "next_mission")
        self.assertEqual(codes, ["01", "02", "03", "04", "05"])
        with self.assertRaises(engine.ActionError) as ctx:
            act(self.session, self.host, "next_mission")
        self.assertEqual(ctx.exception.code, "NO_MORE_MISSIONS")
        counts = QuestionRuntime.objects.filter(session=self.session).values_list("question__mission__code", flat=True)
        self.assertEqual([list(counts).count(c) for c in codes], [5, 8, 7, 5, 1])
        act(self.session, self.host, "finish_game")
        self.assertEqual(self.status(), "FINISHED")

    def test_next_mission_can_skip_remaining_questions(self):
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "next_mission")
        self.assertEqual(refresh(self.session).current_mission.code, "02")

    def test_restart_mission_never_double_awards(self):
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        q = current_question(self.session)
        submit(self.client_team, self.session, correct_answer(q))
        act(self.session, self.host, "close_question")
        act(self.session, self.host, "reveal_answer")
        self.assertEqual(scores(self.session)["Vector"], 100)
        act(self.session, self.host, "restart_mission")
        s = refresh(self.session)
        self.assertEqual((s.status, s.current_runtime_id), ("MISSION_INTRO", None))
        act(self.session, self.host, "start_question")
        rt = refresh(self.session).current_runtime
        self.assertEqual(rt.attempt, 2)
        self.assertEqual(submit(self.client_team, self.session, correct_answer(q)).status_code, 201)
        act(self.session, self.host, "close_question")
        act(self.session, self.host, "reveal_answer")
        self.assertEqual(scores(self.session)["Vector"], 100)
        self.assertEqual(ScoreEvent.objects.filter(source="QUESTION").count(), 1)

    def test_finish_and_archive(self):
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        act(self.session, self.host, "finish_game")
        s = refresh(self.session)
        self.assertEqual(s.status, "FINISHED")
        self.assertIsNotNone(s.finished_at)
        self.assertEqual(QuestionRuntime.objects.get().status, "SKIPPED")
        with self.assertRaises(engine.ActionError):
            act(self.session, self.host, "start_question")
        # Score corrections remain possible after the game ends.
        act(self.session, self.host, "adjust_score", {"team_id": self.team.pk, "points": -20, "reason": "Correction"})
        act(self.session, self.host, "archive")
        self.assertEqual(self.status(), "ARCHIVED")
        with self.assertRaises(engine.ActionError):
            act(self.session, self.host, "adjust_score", {"team_id": self.team.pk, "points": 5, "reason": "x"})

    def test_actions_are_logged(self):
        act(self.session, self.host, "start_game")
        kinds = list(self.session.events.values_list("kind", flat=True))
        self.assertIn("start_game", kinds)
        self.assertEqual(self.session.events.get(kind="start_game").actor, self.host)

    def test_action_api_round_trip(self):
        client = host_client(self.host)
        url = f"/api/host/sessions/{self.session.pk}/action/"
        ok = client.post(url, data=json.dumps({"action": "start_game", "expected_status": "LOBBY", "request_id": "r1"}), content_type="application/json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["result"]["duplicate"], False)
        bad = client.post(url, data=json.dumps({"action": "reveal_answer", "expected_status": "MISSION_INTRO"}), content_type="application/json")
        self.assertEqual(bad.status_code, 409)
        self.assertEqual(bad.json()["error"]["code"], "INVALID_TRANSITION")
        unknown = client.post(url, data=json.dumps({"action": "explode"}), content_type="application/json")
        self.assertEqual(unknown.status_code, 400)
        garbage = client.post(url, data="not json", content_type="application/json")
        self.assertEqual(garbage.status_code, 400)

    def test_host_api_requires_csrf(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.host)
        response = client.post(
            f"/api/host/sessions/{self.session.pk}/action/",
            data=json.dumps({"action": "start_game", "expected_status": "LOBBY"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(GameSession.objects.get(pk=self.session.pk).status, "LOBBY")


class WrongAnswerHelperTests(TestCase):
    """Sanity check of the test helpers against every real question."""

    def test_helpers_produce_correct_and_incorrect_answers(self):
        from games.models import Question
        from live.grading import is_correct, normalize_answer

        for q in Question.objects.all():
            keys = list(q.options.values_list("key", flat=True))
            self.assertTrue(is_correct(q, normalize_answer(q, keys, correct_answer(q))), q)
            self.assertFalse(is_correct(q, normalize_answer(q, keys, wrong_answer(q))), q)
