"""
JSON polling and action endpoints.

Polling protocol: clients send `?v=<last version>` (projector: `?etag=`). When nothing changed
the server answers with a tiny `{"changed": false, ...}` body that still carries `server_time`
so countdowns stay synchronised to the server clock.
"""

import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from . import engine, serializers, services
from .auth import current_team, host_api
from .grading import AnswerFormatError
from .models import GameSession, TeamStatus


def ok(payload, status=200):
    return JsonResponse({"ok": True, **payload}, status=status)


def fail(code, message, status=400, **extra):
    return JsonResponse({"ok": False, "error": {"code": code, "message": message, **extra}}, status=status)


def _json_body(request):
    if len(request.body) > 8192:
        raise ValueError("Request too large")
    data = json.loads(request.body or b"{}")
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def _client_version(request, name="v"):
    try:
        return int(request.GET.get(name, ""))
    except ValueError:
        return None


# --- Team -------------------------------------------------------------------


@never_cache
@require_GET
def team_state(request):
    team = current_team(request)
    if team is None:
        return fail("NO_TEAM", "Not joined to a session.", 401)
    now = timezone.now()
    if team.status == TeamStatus.ACTIVE:
        services.touch_presence(team, now)
    session = team.session
    if _client_version(request) == session.version:
        return ok({"changed": False, "version": session.version, "server_time": serializers.ms(now)})
    return ok({"changed": True, "state": serializers.team_state(team, now)})


@never_cache
@require_POST
def team_submit(request):
    team = current_team(request)
    if team is None:
        return fail("NO_TEAM", "Not joined to a session.", 401)
    try:
        body = _json_body(request)
    except (ValueError, json.JSONDecodeError):
        return fail("BAD_REQUEST", "Invalid request.", 400)
    try:
        submission, created = services.submit_answer(team, body.get("runtime_id"), body.get("answer"))
    except AnswerFormatError as exc:
        return fail("BAD_ANSWER", str(exc), 400)
    except services.ServiceError as exc:
        return fail(exc.code, exc.message, exc.status)
    return ok(
        {
            "accepted": True,
            "duplicate": not created,
            "answer": submission.answer,
            "submitted_at": serializers.ms(submission.submitted_at),
        },
        status=201 if created else 200,
    )


# --- Projector --------------------------------------------------------------


@never_cache
@require_GET
def display_state(request, token):
    session = services.session_for_display_token(token)
    if session is None:
        return fail("DISPLAY_EXPIRED", "This display link has expired. Reopen it from the dashboard.", 401)
    now = timezone.now()
    teams = list(session.teams.filter(status=TeamStatus.ACTIVE))
    etag = f"{session.version}:{services.presence_signature(teams, now)}"
    if request.GET.get("etag") == etag:
        return ok({"changed": False, "etag": etag, "server_time": serializers.ms(now)})
    return ok({"changed": True, "state": serializers.display_state(session, teams=teams, now=now)})


# --- Host -------------------------------------------------------------------


@never_cache
@require_GET
@host_api
def host_state(request, session_id):
    session = get_object_or_404(GameSession.objects.select_related("current_mission"), pk=session_id)
    return ok({"state": serializers.host_state(session)})


@never_cache
@require_POST
@host_api
def host_action(request, session_id):
    get_object_or_404(GameSession, pk=session_id)
    try:
        body = _json_body(request)
    except (ValueError, json.JSONDecodeError):
        return fail("BAD_REQUEST", "Invalid request.", 400)
    expected_runtime = body["expected_runtime"] if "expected_runtime" in body else "__any__"
    try:
        result = engine.perform(
            session_id,
            request.user,
            str(body.get("action", "")),
            params=body.get("params") if isinstance(body.get("params"), dict) else {},
            request_id=str(body.get("request_id") or ""),
            expected_status=body.get("expected_status"),
            expected_runtime=expected_runtime,
        )
    except services.ServiceError as exc:
        return fail(exc.code, exc.message, exc.status)
    return ok({"result": result})


def healthz(request):
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:  # pragma: no cover - only when the database is down
        return JsonResponse({"status": "error", "database": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})
