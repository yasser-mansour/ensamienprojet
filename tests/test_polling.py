import json
from datetime import timedelta

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from live import services
from live.models import DisplayToken

from .helpers import act, correct_answer, current_question, host_client, join, make_host, new_session, submit, team_client


class PollingTests(TestCase):
    def setUp(self):
        self.host = make_host()
        self.session = new_session(self.host)
        self.team, token = join(self.session, "Vector")
        self.client_team = team_client(token)
        self.raw_display = services.create_display_token(self.session)
        self.display_url = f"/api/display/{self.raw_display}/state/"
        self.host_api = host_client(self.host)

    def team_state(self, v=None):
        url = "/api/live/state/" + (f"?v={v}" if v is not None else "")
        response = self.client_team.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        return response.json()

    def test_version_minimal_response(self):
        full = self.team_state()
        self.assertTrue(full["changed"])
        version = full["state"]["version"]
        same = self.team_state(version)
        self.assertEqual(same, {"ok": True, "changed": False, "version": version, "server_time": same["server_time"]})
        act(self.session, self.host, "start_game")
        changed = self.team_state(version)
        self.assertTrue(changed["changed"])
        self.assertEqual(changed["state"]["phase"], "MISSION_INTRO")
        self.assertGreater(changed["state"]["version"], version)

    def test_team_lobby_state(self):
        state = self.team_state()["state"]
        self.assertEqual(state["phase"], "LOBBY")
        self.assertEqual(state["team"]["name"], "Vector")
        self.assertEqual(state["team"]["score"], 0)

    def test_answer_key_hidden_from_teams_and_projector_until_reveal(self):
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        q = current_question(self.session)
        for payload in (self.team_state()["state"], self.client_team.get(self.display_url).json()["state"]):
            text = json.dumps(payload)
            self.assertNotIn("answer_key", text)
            self.assertNotIn("explanation", text)
            self.assertNotIn(q.answer_display, json.dumps({k: v for k, v in payload.items() if k != "question"}))
            self.assertIn("question", payload)
        host_state = self.host_api.get(f"/api/host/sessions/{self.session.pk}/state/").json()["state"]
        self.assertEqual(host_state["question"]["answer_key"], q.answer_key)
        submit(self.client_team, self.session, correct_answer(q))
        act(self.session, self.host, "close_question")
        self.assertNotIn("answer_key", json.dumps(self.team_state()["state"]))
        act(self.session, self.host, "reveal_answer")
        revealed = self.team_state()["state"]
        self.assertEqual(revealed["reveal"]["answer_key"], q.answer_key)
        self.assertTrue(revealed["reveal"]["correct"])
        self.assertEqual(revealed["reveal"]["points_awarded"], 100)
        display = self.client_team.get(self.display_url).json()["state"]
        self.assertEqual(display["reveal"]["correct_count"], 1)
        self.assertEqual(display["reveal"]["results"], [{"name": "Vector", "correct": True}])

    def test_team_never_sees_other_teams_answers(self):
        other, other_token = join(self.session, "Nova")
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        q = current_question(self.session)
        submit(team_client(other_token), self.session, correct_answer(q))
        state = self.team_state()["state"]
        self.assertIsNone(state["my_submission"])
        self.assertNotIn("Nova", json.dumps(state))

    def test_display_state_and_etag(self):
        first = self.client.get(self.display_url).json()
        self.assertTrue(first["changed"])
        state = first["state"]
        self.assertEqual(state["code"], self.session.code)
        self.assertEqual(state["teams"], [{"name": "Vector", "slot": 1, "connected": True}])
        self.assertNotIn("team_table", state)
        self.assertNotIn("events", state)
        same = self.client.get(self.display_url + f"?etag={state['etag']}").json()
        self.assertFalse(same["changed"])
        join(self.session, "Apollo")
        changed = self.client.get(self.display_url + f"?etag={state['etag']}").json()
        self.assertTrue(changed["changed"])
        self.assertEqual(len(changed["state"]["teams"]), 2)

    def test_display_token_scoped_and_expiring(self):
        self.assertEqual(self.client.get("/api/display/forged/state/").status_code, 401)
        self.assertEqual(self.client.get("/display/forged/").status_code, 404)
        page = self.client.get(f"/display/{self.raw_display}/")
        self.assertContains(page, self.session.code)
        self.assertContains(page, "<svg")  # QR code
        DisplayToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get(self.display_url).status_code, 401)
        # A display token never grants host powers.
        self.assertEqual(self.client.get(f"/api/host/sessions/{self.session.pk}/state/").status_code, 403)

    def test_host_and_projector_stay_synchronised(self):
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        host_state = self.host_api.get(f"/api/host/sessions/{self.session.pk}/state/").json()["state"]
        display = self.client.get(self.display_url).json()["state"]
        team = self.team_state()["state"]
        self.assertEqual(host_state["version"], display["version"])
        self.assertEqual(host_state["version"], team["version"])
        for key in ("runtime_id", "deadline", "label"):
            self.assertEqual(host_state["question"][key], display["question"][key])
            self.assertEqual(host_state["question"][key], team["question"][key])
        submit(self.client_team, self.session, correct_answer(current_question(self.session)))
        display = self.client.get(self.display_url).json()["state"]
        host_state = self.host_api.get(f"/api/host/sessions/{self.session.pk}/state/").json()["state"]
        self.assertEqual(display["submissions"], {"count": 1, "total": 1})
        self.assertEqual(host_state["submissions"], {"count": 1, "total": 1})
        self.assertTrue(host_state["team_table"][0]["submitted"])

    def test_host_state_contents(self):
        state = self.host_api.get(f"/api/host/sessions/{self.session.pk}/state/").json()["state"]
        self.assertIn("start_game", state["allowed_actions"])
        self.assertEqual(state["team_table"][0]["name"], "Vector")
        self.assertEqual(len(state["missions"]), 5)
        self.assertTrue(state["events"])

    def test_presence_updates_last_seen(self):
        from live.models import TeamParticipation

        TeamParticipation.objects.filter(pk=self.team.pk).update(last_seen=timezone.now() - timedelta(seconds=30))
        host_state = self.host_api.get(f"/api/host/sessions/{self.session.pk}/state/").json()["state"]
        self.assertFalse(host_state["team_table"][0]["connected"])
        self.team_state()
        host_state = self.host_api.get(f"/api/host/sessions/{self.session.pk}/state/").json()["state"]
        self.assertTrue(host_state["team_table"][0]["connected"])

    def test_server_time_supplied_for_clock_sync(self):
        before = int(timezone.now().timestamp() * 1000)
        state = self.team_state()["state"]
        self.assertGreaterEqual(state["server_time"], before)


class QueryBudgetTests(TestCase):
    """Polling must stay cheap: ~10 phones + host + projector poll every second."""

    def setUp(self):
        self.host = make_host()
        self.session = new_session(self.host)
        self.tokens = [join(self.session, f"Team {i}")[1] for i in range(8)]
        self.raw_display = services.create_display_token(self.session)
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")

    def count(self, client, url):
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(url)
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries), response.json()

    def test_unchanged_team_poll_is_one_or_two_queries(self):
        client = team_client(self.tokens[0])
        _, full = self.count(client, "/api/live/state/")
        n, data = self.count(client, f"/api/live/state/?v={full['state']['version']}")
        self.assertFalse(data["changed"])
        self.assertLessEqual(n, 2)

    def test_full_poll_budgets(self):
        n_team, _ = self.count(team_client(self.tokens[0]), "/api/live/state/")
        n_display, _ = self.count(Client(), f"/api/display/{self.raw_display}/state/")
        n_host, _ = self.count(host_client(self.host), f"/api/host/sessions/{self.session.pk}/state/")
        self.assertLessEqual(n_team, 10)
        self.assertLessEqual(n_display, 10)
        self.assertLessEqual(n_host, 25)

    def test_unchanged_display_poll_is_cheap(self):
        client = Client()
        _, full = self.count(client, f"/api/display/{self.raw_display}/state/")
        n, data = self.count(client, f"/api/display/{self.raw_display}/state/?etag={full['state']['etag']}")
        self.assertFalse(data["changed"])
        self.assertLessEqual(n, 3)
