import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase

from .helpers import HOST_EMAIL, HOST_PASSWORD, join, make_host, new_session, team_client


class HostAuthenticationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.host = make_host()

    def test_login_page_renders(self):
        response = self.client.get("/host/login/")
        self.assertContains(response, "Host sign in")
        self.assertContains(response, 'name="email"')

    def test_successful_login_redirects_to_dashboard(self):
        response = self.client.post("/host/login/", {"email": HOST_EMAIL, "password": HOST_PASSWORD})
        self.assertRedirects(response, "/host/")
        self.assertContains(self.client.get("/host/"), "No active session")

    def test_email_is_case_insensitive(self):
        response = self.client.post("/host/login/", {"email": HOST_EMAIL.upper(), "password": HOST_PASSWORD})
        self.assertRedirects(response, "/host/")

    def test_wrong_password_shows_generic_error(self):
        response = self.client.post("/host/login/", {"email": HOST_EMAIL, "password": "nope"})
        self.assertEqual(response.status_code, 401)
        self.assertContains(response, "Incorrect e-mail or password.", status_code=401)

    def test_unknown_email_shows_same_generic_error(self):
        response = self.client.post("/host/login/", {"email": "who@example.com", "password": "nope"})
        self.assertContains(response, "Incorrect e-mail or password.", status_code=401)

    def test_non_staff_user_cannot_sign_in(self):
        get_user_model().objects.create_user(username="s@example.com", email="s@example.com", password=HOST_PASSWORD)
        response = self.client.post("/host/login/", {"email": "s@example.com", "password": HOST_PASSWORD})
        self.assertEqual(response.status_code, 401)

    def test_login_rate_limited_after_repeated_failures(self):
        for _ in range(5):
            self.client.post("/host/login/", {"email": HOST_EMAIL, "password": "wrong"})
        response = self.client.post("/host/login/", {"email": HOST_EMAIL, "password": HOST_PASSWORD})
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Too many sign-in attempts", status_code=429)

    def test_rate_limiter_fails_open_when_cache_is_down(self):
        from unittest import mock

        with mock.patch("accounts.ratelimit.cache.get", side_effect=RuntimeError("cache down")), mock.patch(
            "accounts.ratelimit.cache.add", side_effect=RuntimeError("cache down")
        ), self.assertLogs("accounts.ratelimit", level="ERROR"):
            response = self.client.post("/host/login/", {"email": HOST_EMAIL, "password": HOST_PASSWORD})
        self.assertRedirects(response, "/host/")

    def test_spoofed_forwarded_for_does_not_evade_limit(self):
        for i in range(5):
            self.client.post("/host/login/", {"email": HOST_EMAIL, "password": "wrong"}, HTTP_X_FORWARDED_FOR=f"10.0.0.{i}")
        response = self.client.post("/host/login/", {"email": HOST_EMAIL, "password": HOST_PASSWORD})
        self.assertEqual(response.status_code, 429)

    def test_open_redirect_is_blocked(self):
        response = self.client.post(
            "/host/login/", {"email": HOST_EMAIL, "password": HOST_PASSWORD, "next": "https://evil.example/"}
        )
        self.assertRedirects(response, "/host/")

    def test_logout_requires_post(self):
        self.client.force_login(self.host)
        self.assertEqual(self.client.get("/host/logout/").status_code, 405)
        self.assertRedirects(self.client.post("/host/logout/"), "/host/login/")
        self.assertEqual(self.client.get("/host/").status_code, 302)

    def test_login_form_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post("/host/login/", {"email": HOST_EMAIL, "password": HOST_PASSWORD})
        self.assertEqual(response.status_code, 403)


class UnauthorizedHostAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        self.host = make_host()
        self.session = new_session(self.host)

    def test_host_pages_redirect_anonymous_users_to_login(self):
        for url in ["/host/", f"/host/sessions/{self.session.pk}/", "/host/history/", f"/host/sessions/{self.session.pk}/report/"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response["Location"].startswith("/host/login/"), url)

    def test_create_session_requires_host(self):
        response = self.client.post("/host/sessions/new/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/host/login/"))

    def test_host_api_rejects_anonymous_and_team_clients(self):
        _, token = join(self.session, "Vector")
        for client in (Client(), team_client(token)):
            state = client.get(f"/api/host/sessions/{self.session.pk}/state/")
            self.assertEqual(state.status_code, 403)
            action = client.post(
                f"/api/host/sessions/{self.session.pk}/action/",
                data=json.dumps({"action": "start_game", "expected_status": "LOBBY"}),
                content_type="application/json",
            )
            self.assertEqual(action.status_code, 403)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, "LOBBY")

    def test_non_staff_logged_in_user_is_rejected(self):
        user = get_user_model().objects.create_user(username="x@example.com", email="x@example.com", password="x")
        client = Client()
        client.force_login(user)
        self.assertEqual(client.get(f"/api/host/sessions/{self.session.pk}/state/").status_code, 403)
        self.assertEqual(client.get("/host/").status_code, 302)

    def test_projector_open_requires_host(self):
        response = self.client.post(f"/host/sessions/{self.session.pk}/display/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/host/login/"))
