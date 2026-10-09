"""HTML pages: the public join flow, the team app shell, the host dashboard, projector and history."""

from collections import defaultdict

import segno
from django.conf import settings
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from accounts import ratelimit

from . import grading, services
from .auth import current_team, host_required, set_team_cookie
from .models import CLOSED_STATUSES, GameSession, QuestionRuntime, ScoreEvent, TeamStatus

CONF = settings.ENSAMIEN
JOIN_SESSION_KEY = "join_session_id"


def public_base_url(request):
    return settings.PUBLIC_BASE_URL or request.build_absolute_uri("/").rstrip("/")


def _join_limited(request):
    return ratelimit.is_limited("join-ip", ratelimit.client_ip(request), CONF["JOIN_LIMIT_PER_IP"]) or (
        request.session.session_key
        and ratelimit.is_limited("join-client", request.session.session_key, CONF["JOIN_LIMIT_PER_CLIENT"])
    )


def _join_failed(request):
    if not request.session.session_key:
        request.session.save()
    ratelimit.register_failure("join-ip", ratelimit.client_ip(request), CONF["JOIN_LIMIT_PER_IP"])
    ratelimit.register_failure("join-client", request.session.session_key, CONF["JOIN_LIMIT_PER_CLIENT"])


# --- Public / team ----------------------------------------------------------


@never_cache
@ensure_csrf_cookie
def home(request):
    team = current_team(request)
    if team is not None and team.status == TeamStatus.ACTIVE and team.session.status not in CLOSED_STATUSES:
        return redirect("live:play")
    error = None
    status = 200
    if request.method == "POST":
        if _join_limited(request):
            error, status = "TOO MANY ATTEMPTS — WAIT A MINUTE", 429
        else:
            try:
                session = services.find_joinable_session(request.POST.get("code"))
            except services.ServiceError as exc:
                if exc.code == "INVALID_CODE":
                    _join_failed(request)
                error, status = exc.message, exc.status
            else:
                request.session[JOIN_SESSION_KEY] = session.pk
                return redirect("live:join_team")
    return render(request, "team/home.html", {"error": error}, status=status)


def _pending_join_session(request):
    session_id = request.session.get(JOIN_SESSION_KEY)
    if not session_id:
        return None
    return GameSession.objects.filter(pk=session_id).exclude(status__in=CLOSED_STATUSES).first()


@never_cache
def join_team(request):
    session = _pending_join_session(request)
    if session is None:
        return redirect("live:home")
    error, status, name = None, 200, ""
    if request.method == "POST":
        name = request.POST.get("team_name", "")[:200]
        try:
            team, raw_token = services.join_team(session.pk, name)
        except services.ServiceError as exc:
            error, status = exc.message, exc.status
            if exc.code in ("INVALID_CODE", "EXPIRED", "REGISTRATION_CLOSED", "FULL"):
                request.session.pop(JOIN_SESSION_KEY, None)
                return render(request, "team/home.html", {"error": exc.message}, status=status)
        else:
            request.session.pop(JOIN_SESSION_KEY, None)
            response = redirect("live:play")
            return set_team_cookie(response, raw_token, settings.SESSION_COOKIE_SECURE)
    return render(
        request,
        "team/join_team.html",
        {"error": error, "name": name, "max_length": CONF["TEAM_NAME_MAX_LENGTH"], "code": session.code},
        status=status,
    )


@never_cache
def join_recover(request):
    session = _pending_join_session(request)
    if session is None:
        return redirect("live:home")
    error, status = None, 200
    if request.method == "POST":
        if _join_limited(request):
            error, status = "TOO MANY ATTEMPTS — WAIT A MINUTE", 429
        else:
            try:
                team, raw_token = services.recover_team(session.pk, request.POST.get("recovery_code"))
            except services.ServiceError as exc:
                _join_failed(request)
                error, status = exc.message, exc.status
            else:
                request.session.pop(JOIN_SESSION_KEY, None)
                return set_team_cookie(redirect("live:play"), raw_token, settings.SESSION_COOKIE_SECURE)
    return render(request, "team/recover.html", {"error": error, "code": session.code}, status=status)


@never_cache
@ensure_csrf_cookie
def play(request):
    team = current_team(request)
    if team is None:
        return redirect("live:home")
    return render(request, "team/play.html", {"team": team})


@require_POST
def leave(request):
    """Forget this device's team credential (the team keeps its slot and score)."""
    response = redirect("live:home")
    response.delete_cookie(CONF["TEAM_COOKIE_NAME"], samesite="Lax")
    return response


# --- Host -------------------------------------------------------------------


@host_required
@never_cache
def host_dashboard(request):
    active = GameSession.objects.exclude(status__in=CLOSED_STATUSES).annotate(
        team_count=Count("teams", filter=Q(teams__status=TeamStatus.ACTIVE))
    )
    past = GameSession.objects.filter(status__in=CLOSED_STATUSES).annotate(
        team_count=Count("teams", filter=Q(teams__status=TeamStatus.ACTIVE))
    )[:20]
    return render(request, "live/host_dashboard.html", {"active_sessions": active, "past_sessions": past})


@host_required
@require_POST
def host_create_session(request):
    session = services.create_session(request.user)
    return redirect("live:host_control", session_id=session.pk)


@host_required
@never_cache
@ensure_csrf_cookie
def host_control(request, session_id):
    session = get_object_or_404(GameSession, pk=session_id)
    return render(
        request,
        "live/host_control.html",
        {"session": session, "public_url": public_base_url(request)},
    )


@host_required
@require_POST
def host_open_display(request, session_id):
    session = get_object_or_404(GameSession, pk=session_id)
    raw = services.create_display_token(session)
    return redirect("live:display", token=raw)


@host_required
@never_cache
def host_history(request):
    sessions = GameSession.objects.annotate(
        team_count=Count("teams", filter=Q(teams__status=TeamStatus.ACTIVE))
    ).order_by("-created_at")
    return render(request, "live/host_history.html", {"sessions": sessions})


@host_required
@never_cache
def host_report(request, session_id):
    session = get_object_or_404(GameSession.objects.select_related("experience"), pk=session_id)
    teams = list(session.teams.order_by("slot"))
    board = services.leaderboard(session, teams=[t for t in teams if t.status == TeamStatus.ACTIVE])
    scores = services.team_scores(session)

    runtimes = list(
        QuestionRuntime.objects.filter(session=session)
        .select_related("question__mission")
        .prefetch_related("submissions__team", "question__options")
        .order_by("opened_at")
    )
    rows = []
    mission_results = defaultdict(lambda: defaultdict(lambda: {"correct": 0, "answered": 0}))
    for rt in runtimes:
        option_text = {o.key: o.text for o in rt.question.options.all()}
        by_team = {s.team_id: s for s in rt.submissions.all()}
        cells = []
        for t in teams:
            sub = by_team.get(t.pk)
            if sub is not None:
                agg = mission_results[rt.question.mission.code][t.pk]
                agg["answered"] += 1
                agg["correct"] += int(sub.is_correct)
            cells.append(
                {
                    "answer": grading.describe_answer(rt.question, sub.answer, option_text) if sub else None,
                    "correct": sub.is_correct if sub else None,
                    "counted": rt.status == "REVEALED",
                }
            )
        rows.append({"runtime": rt, "cells": cells})

    missions = sorted({rt.question.mission for rt in runtimes}, key=lambda m: m.order)
    mission_table = [
        {
            "mission": m,
            "cells": [mission_results[m.code].get(t.pk, {"correct": 0, "answered": 0}) for t in teams],
        }
        for m in missions
    ]
    context = {
        "session": session,
        "teams": teams,
        "team_scores": [{"team": t, "score": scores.get(t.pk, 0) or 0} for t in teams],
        "board": board,
        "rows": rows,
        "mission_table": mission_table,
        "manual_events": ScoreEvent.objects.filter(session=session, source="MANUAL").select_related("team", "created_by"),
        "events": session.events.order_by("created_at", "id"),
    }
    return render(request, "live/host_report.html", context)


# --- Projector --------------------------------------------------------------


@never_cache
@ensure_csrf_cookie
def display(request, token):
    session = services.session_for_display_token(token)
    if session is None:
        raise Http404("Display link expired")
    join_url = public_base_url(request)
    qr_svg = segno.make(join_url, error="m").svg_inline(omitsize=True, dark="#0E1116", light="#F4F6F8", border=2)
    return render(
        request,
        "live/display.html",
        {
            "session": session,
            "token": token,
            "join_url": join_url,
            "join_host": join_url.split("://", 1)[-1],
            "qr_svg": qr_svg,
            "state_url": reverse("live:api_display_state", kwargs={"token": token}),
        },
    )
