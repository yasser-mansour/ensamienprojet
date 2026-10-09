import json

from django.contrib.auth import get_user_model
from django.test import Client

from live import engine, services
from live.models import GameSession

HOST_EMAIL = "host@example.com"
HOST_PASSWORD = "Correct-Horse-Battery-9"


def make_host(email=HOST_EMAIL, password=HOST_PASSWORD, **extra):
    User = get_user_model()
    defaults = {"is_staff": True, "is_superuser": True}
    defaults.update(extra)
    return User.objects.create_user(username=email, email=email, password=password, **defaults)


def host_client(user):
    client = Client()
    client.force_login(user)
    return client


def new_session(host):
    return services.create_session(host)


def join(session, name):
    """Join through the service layer; returns (team, raw_token)."""
    return services.join_team(session.pk, name)


def team_client(raw_token):
    client = Client()
    client.cookies["ensamien_team"] = raw_token
    return client


def act(session, host, action, params=None, request_id=""):
    """Perform a host action using the session's current state as the expected state."""
    session = GameSession.objects.get(pk=session.pk)
    return engine.perform(
        session.pk,
        host,
        action,
        params=params or {},
        request_id=request_id,
        expected_status=session.status,
        expected_runtime=session.current_runtime_id,
    )


def refresh(session):
    return GameSession.objects.get(pk=session.pk)


def current_question(session):
    session = refresh(session)
    return session.current_runtime.question if session.current_runtime_id else None


def correct_answer(question):
    key = question.answer_key
    if question.kind == "MATCH":
        return {"pairs": dict(key)}
    if question.kind == "ORDER":
        return {"order": list(key)}
    return {"option": key}


def wrong_answer(question):
    key = question.answer_key
    if question.kind == "MATCH":
        pairs = dict(key)
        a, b = list(pairs)[:2]
        pairs[a], pairs[b] = pairs[b], pairs[a]
        return {"pairs": pairs}
    if question.kind == "ORDER":
        order = list(key)
        order[0], order[1] = order[1], order[0]
        return {"order": order}
    other = question.options.exclude(key=key).first()
    return {"option": other.key}


def submit(client, session, answer):
    session = refresh(session)
    return client.post(
        "/api/live/submit/",
        data=json.dumps({"runtime_id": session.current_runtime_id, "answer": answer}),
        content_type="application/json",
    )


def scores(session):
    return {row["name"]: row["score"] for row in services.leaderboard(refresh(session))}
