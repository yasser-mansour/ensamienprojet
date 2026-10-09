from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from live import services
from live.models import GameSession, TeamParticipation

from .helpers import act, host_client, join, make_host, new_session, team_client


class SessionCreationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.host = make_host()

    def test_create_session_via_dashboard(self):
        client = host_client(self.host)
        response = client.post("/host/sessions/new/")
        session = GameSession.objects.get()
        self.assertRedirects(response, f"/host/sessions/{session.pk}/")
        self.assertEqual(session.status, "LOBBY")
        self.assertTrue(session.registration_open)
        self.assertRegex(session.code, r"^\d{6}$")
        self.assertEqual(session.version, 1)
        self.assertTrue(session.events.filter(kind="create_session").exists())
        page = client.get(f"/host/sessions/{session.pk}/")
        self.assertContains(page, session.code)

    def test_codes_are_six_digits_and_random(self):
        codes = {new_session(self.host).code for _ in range(30)}
        self.assertTrue(all(len(c) == 6 and c.isdigit() for c in codes))
        self.assertGreater(len(codes), 25)

    def test_code_collision_with_open_session_is_retried(self):
        first = new_session(self.host)
        with mock.patch("live.tokens.new_join_code", side_effect=[first.code, first.code, "123456"]):
            second = new_session(self.host)
        self.assertEqual(second.code, "123456")

    def test_code_of_finished_session_can_be_reused(self):
        first = new_session(self.host)
        join(first, "A")
        act(first, self.host, "finish_game")
        with mock.patch("live.tokens.new_join_code", return_value=first.code):
            second = new_session(self.host)
        self.assertEqual(second.code, first.code)

    def test_new_session_does_not_touch_history(self):
        first = new_session(self.host)
        join(first, "A")
        act(first, self.host, "finish_game")
        new_session(self.host)
        self.assertEqual(GameSession.objects.count(), 2)
        self.assertEqual(TeamParticipation.objects.filter(session=first).count(), 1)


class JoinFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.host = make_host()
        self.session = new_session(self.host)

    def enter_code(self, client, code):
        return client.post("/", {"code": code})

    def test_full_join_flow_sets_httponly_cookie(self):
        client = Client()
        response = self.enter_code(client, self.session.code)
        self.assertRedirects(response, "/join/team/")
        response = client.post("/join/team/", {"team_name": "  Team   Vector "})
        self.assertRedirects(response, "/play/", fetch_redirect_response=False)
        cookie = response.cookies["ensamien_team"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        team = TeamParticipation.objects.get()
        self.assertEqual(team.name, "Team Vector")
        self.assertNotEqual(team.token_hash, cookie.value)  # only the digest is stored
        self.assertEqual(client.get("/play/").status_code, 200)

    def test_code_with_spaces_or_dashes_is_accepted(self):
        formatted = f"{self.session.code[:3]} {self.session.code[3:]}"
        self.assertRedirects(self.enter_code(Client(), formatted), "/join/team/")

    def test_invalid_code(self):
        for code in ["", "12345", "abcdef", "1234567"]:
            response = self.enter_code(Client(), code)
            self.assertContains(response, "INVALID SESSION CODE", status_code=400)
        wrong = "000000" if self.session.code != "000000" else "111111"
        self.assertContains(self.enter_code(Client(), wrong), "INVALID SESSION CODE", status_code=400)

    def test_finished_session_code_looks_invalid(self):
        join(self.session, "A")
        act(self.session, self.host, "finish_game")
        self.assertContains(self.enter_code(Client(), self.session.code), "INVALID SESSION CODE", status_code=400)

    def test_expired_session(self):
        GameSession.objects.filter(pk=self.session.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertContains(self.enter_code(Client(), self.session.code), "SESSION EXPIRED", status_code=410)

    def test_registration_closed(self):
        act(self.session, self.host, "close_registration")
        self.assertContains(self.enter_code(Client(), self.session.code), "REGISTRATION CLOSED", status_code=403)

    def test_registration_closes_between_code_and_name(self):
        client = Client()
        self.enter_code(client, self.session.code)
        act(self.session, self.host, "close_registration")
        response = client.post("/join/team/", {"team_name": "Late"})
        self.assertContains(response, "REGISTRATION CLOSED", status_code=403)
        self.assertFalse(TeamParticipation.objects.exists())

    def test_team_name_page_requires_valid_code_first(self):
        self.assertRedirects(Client().get("/join/team/"), "/")

    def test_join_code_rate_limit(self):
        client = Client()
        for _ in range(8):
            self.enter_code(client, "999999" if self.session.code != "999999" else "888888")
        response = self.enter_code(client, self.session.code)
        self.assertContains(response, "TOO MANY ATTEMPTS", status_code=429)

    def test_returning_device_is_sent_back_to_play(self):
        _, token = join(self.session, "Vector")
        response = team_client(token).get("/")
        self.assertRedirects(response, "/play/")


class TeamNameValidationTests(TestCase):
    def setUp(self):
        self.host = make_host()
        self.session = new_session(self.host)

    def assertRejected(self, name, code="NAME_INVALID"):
        with self.assertRaises(services.ServiceError) as ctx:
            join(self.session, name)
        self.assertEqual(ctx.exception.code, code)

    def test_empty_and_whitespace_names_rejected(self):
        self.assertRejected("")
        self.assertRejected("     ")

    def test_too_long_name_rejected(self):
        self.assertRejected("X" * 25)
        team, _ = join(self.session, "X" * 24)
        self.assertEqual(len(team.name), 24)

    def test_html_and_control_characters_rejected(self):
        self.assertRejected("<script>alert(1)</script>")
        self.assertRejected("Team\u0000Null")
        self.assertRejected("Team‮RTL")

    def test_whitespace_trimmed_and_collapsed(self):
        team, _ = join(self.session, "   Apollo    Eleven  ")
        self.assertEqual(team.name, "Apollo Eleven")

    def test_duplicate_names_case_insensitive(self):
        join(self.session, "Nova")
        self.assertRejected("NOVA", "NAME_TAKEN")
        self.assertRejected("  nova ", "NAME_TAKEN")
        self.assertRejected("ｎｏｖａ", "NAME_TAKEN")  # full-width characters normalise to the same name

    def test_same_name_allowed_in_another_session(self):
        join(self.session, "Nova")
        other = new_session(self.host)
        team, _ = join(other, "Nova")
        self.assertEqual(team.name, "Nova")

    def test_names_are_escaped_when_rendered(self):
        team, token = join(self.session, "A&B \"quoted\" 'x'")
        page = team_client(token).get("/play/")
        self.assertContains(page, "A&amp;B &quot;quoted&quot; &#x27;x&#x27;")


class CapacityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.host = make_host()
        self.session = new_session(self.host)

    def test_ten_slots_then_full(self):
        teams = [join(self.session, f"Team {i}")[0] for i in range(10)]
        self.assertEqual(sorted(t.slot for t in teams), list(range(1, 11)))
        with self.assertRaises(services.ServiceError) as ctx:
            join(self.session, "Eleven")
        self.assertEqual(ctx.exception.code, "FULL")
        response = Client().post("/", {"code": self.session.code})
        self.assertContains(response, "SESSION FULL", status_code=409)

    def test_removing_a_team_reopens_its_slot(self):
        teams = [join(self.session, f"Team {i}")[0] for i in range(10)]
        act(self.session, self.host, "remove_team", {"team_id": teams[3].pk})
        newcomer, _ = join(self.session, "Newcomer")
        self.assertEqual(newcomer.slot, teams[3].slot)
        # The removed team's name is free again too, and its history row is preserved.
        self.assertEqual(TeamParticipation.objects.filter(session=self.session).count(), 11)


class ReconnectAndRecoveryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.host = make_host()
        self.session = new_session(self.host)
        self.team, self.token = join(self.session, "Titan")

    def test_same_device_reconnects_with_cookie(self):
        client = team_client(self.token)
        self.assertEqual(client.get("/play/").status_code, 200)
        state = client.get("/api/live/state/").json()
        self.assertEqual(state["state"]["team"]["name"], "Titan")

    def test_missing_cookie_cannot_play(self):
        self.assertRedirects(Client().get("/play/"), "/")
        self.assertEqual(Client().get("/api/live/state/").status_code, 401)

    def test_forged_cookie_rejected(self):
        self.assertEqual(team_client("not-a-real-token").get("/api/live/state/").status_code, 401)

    def test_recovery_code_moves_team_to_new_device(self):
        result = act(self.session, self.host, "issue_recovery", {"team_id": self.team.pk})
        code = result["recovery_code"]
        phone = Client()
        phone.post("/", {"code": self.session.code})
        response = phone.post("/join/recover/", {"recovery_code": code.lower()})
        self.assertRedirects(response, "/play/", fetch_redirect_response=False)
        new_token = response.cookies["ensamien_team"].value
        self.assertEqual(team_client(new_token).get("/api/live/state/").json()["state"]["team"]["name"], "Titan")
        # The old device is disconnected and the code is single-use.
        self.assertEqual(team_client(self.token).get("/api/live/state/").status_code, 401)
        other = Client()
        other.post("/", {"code": self.session.code})
        self.assertContains(other.post("/join/recover/", {"recovery_code": code}), "INVALID OR EXPIRED", status_code=400)

    def test_recovery_requires_host_issued_code_not_team_name(self):
        phone = Client()
        phone.post("/", {"code": self.session.code})
        self.assertContains(phone.post("/join/recover/", {"recovery_code": "TITAN"}), "INVALID", status_code=400)
        self.assertContains(phone.post("/join/team/", {"team_name": "titan"}), "ALREADY TAKEN", status_code=409)

    def test_expired_recovery_code_rejected(self):
        code = act(self.session, self.host, "issue_recovery", {"team_id": self.team.pk})["recovery_code"]
        TeamParticipation.objects.filter(pk=self.team.pk).update(recovery_expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(services.ServiceError):
            services.recover_team(self.session.pk, code)

    def test_removed_team_sees_removed_state_and_cannot_submit(self):
        act(self.session, self.host, "remove_team", {"team_id": self.team.pk})
        state = team_client(self.token).get("/api/live/state/").json()["state"]
        self.assertTrue(state["team"]["removed"])
        self.assertNotIn("question", state)

    def test_disconnected_team_keeps_slot_and_score(self):
        TeamParticipation.objects.filter(pk=self.team.pk).update(last_seen=timezone.now() - timedelta(minutes=5))
        self.team.refresh_from_db()
        self.assertFalse(self.team.is_connected())
        self.assertEqual(self.team.status, "ACTIVE")
        team_client(self.token).get("/api/live/state/")
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_connected())
