"""
State payloads for the three kinds of polling clients. Each function returns only what that
role may see:

  * team_state     — one team's view. The answer key and other teams' answers are never
                     included before the host reveals the answer.
  * display_state  — the projector. Public information only; no answer key before reveal.
  * host_state     — the full control view (host only).
"""

from django.db.models import Sum
from django.utils import timezone

from games.models import Mission

from . import engine
from .models import RuntimeStatus, ScoreEvent, SessionEvent, SessionStatus as S, TeamStatus
from .services import leaderboard, presence_signature, runtime_for_session, team_scores

LEADERBOARD_PHASES = {S.LEADERBOARD, S.MISSION_COMPLETE, S.FINISHED, S.ARCHIVED}
QUESTION_PHASES = {S.QUESTION_OPEN, S.QUESTION_CLOSED, S.ANSWER_REVEALED, S.LEADERBOARD}


def ms(dt):
    return int(dt.timestamp() * 1000) if dt else None


def _mission_payload(mission, total):
    if mission is None:
        return None
    return {
        "code": mission.code,
        "order": mission.order,
        "total": total,
        "title": mission.title,
        "objective": mission.objective,
        "briefing": mission.briefing,
        "is_final": mission.is_final,
        "question_count": mission.questions.count(),
        "default_duration": mission.default_duration,
    }


def _question_payload(runtime, now):
    q = runtime.question
    return {
        "runtime_id": runtime.pk,
        "status": runtime.status,
        "attempt": runtime.attempt,
        "kind": q.kind,
        "order": q.order,
        "label": q.label,
        "prompt": q.prompt,
        "context": q.context,
        "items": q.items,
        "options": [{"key": o.key, "text": o.text} for o in q.options.all()],
        "points": q.points,
        "source": q.source,
        "source_reference": q.source_reference,
        "duration_ms": runtime.duration_seconds * 1000,
        "deadline": ms(runtime.deadline),
        "remaining_ms": runtime.remaining_ms(now),
        "paused": runtime.deadline is None and runtime.status == RuntimeStatus.OPEN,
    }


def _reveal_payload(runtime):
    q = runtime.question
    return {
        "answer_key": q.answer_key,
        "answer_display": q.answer_display,
        "explanation": q.explanation,
        "clarification": q.clarification,
    }


def _common(session, now):
    return {
        "version": session.version,
        "server_time": ms(now),
        "status": session.status,
        "phase": session.effective_status,
        "paused": session.status == S.PAUSED,
    }


def _missions_total(session):
    return Mission.objects.filter(experience_id=session.experience_id).count()


def team_state(team, now=None):
    now = now or timezone.now()
    session = team.session
    data = _common(session, now)
    data["team"] = {"name": team.name, "slot": team.slot, "removed": team.status != TeamStatus.ACTIVE}
    data["session_code"] = session.code
    if team.status != TeamStatus.ACTIVE:
        return data

    scores = team_scores(session)
    data["team"]["score"] = scores.get(team.pk, 0) or 0
    phase = session.effective_status
    if session.current_mission_id:
        data["mission"] = _mission_payload(session.current_mission, _missions_total(session))

    runtime = runtime_for_session(session)
    if runtime is not None and phase in QUESTION_PHASES | {S.MISSION_COMPLETE}:
        data["question"] = _question_payload(runtime, now)
        sub = runtime.submissions.filter(team=team).first()
        data["my_submission"] = (
            {"answer": sub.answer, "submitted_at": ms(sub.submitted_at)} if sub is not None else None
        )
        if runtime.status == RuntimeStatus.REVEALED:
            reveal = _reveal_payload(runtime)
            reveal["correct"] = bool(sub and sub.is_correct)
            reveal["points_awarded"] = (
                ScoreEvent.objects.filter(runtime=runtime, team=team, source="QUESTION").aggregate(p=Sum("points"))["p"]
                or 0
            )
            data["reveal"] = reveal

    if phase in LEADERBOARD_PHASES:
        board = leaderboard(session, scores=scores)
        data["leaderboard"] = [{k: r[k] for k in ("name", "score", "rank")} for r in board]
        mine = next((r for r in board if r["team_id"] == team.pk), None)
        data["team"]["rank"] = mine["rank"] if mine else None
        data["team"]["team_count"] = len(board)
    return data


def display_state(session, teams=None, now=None):
    now = now or timezone.now()
    teams = list(session.teams.filter(status=TeamStatus.ACTIVE)) if teams is None else teams
    data = _common(session, now)
    data["etag"] = f"{session.version}:{presence_signature(teams, now)}"
    data.update(
        {
            "code": session.code,
            "registration_open": session.registration_open,
            "max_teams": 10,
            "teams": [
                {"name": t.name, "slot": t.slot, "connected": t.is_connected(now)}
                for t in sorted(teams, key=lambda t: t.joined_at)
            ],
        }
    )
    phase = session.effective_status
    if session.current_mission_id:
        data["mission"] = _mission_payload(session.current_mission, _missions_total(session))
    runtime = runtime_for_session(session)
    if runtime is not None and phase in QUESTION_PHASES | {S.MISSION_COMPLETE}:
        data["question"] = _question_payload(runtime, now)
        subs = list(runtime.submissions.filter(team__status=TeamStatus.ACTIVE).select_related("team"))
        data["submissions"] = {"count": len(subs), "total": len(teams)}
        if runtime.status == RuntimeStatus.REVEALED:
            reveal = _reveal_payload(runtime)
            reveal["results"] = sorted(
                ({"name": s.team.name, "correct": s.is_correct} for s in subs), key=lambda r: (not r["correct"], r["name"])
            )
            reveal["correct_count"] = sum(1 for s in subs if s.is_correct)
            data["reveal"] = reveal
    if phase in LEADERBOARD_PHASES or phase == S.MISSION_COMPLETE:
        board = leaderboard(session, teams=teams)
        data["leaderboard"] = [{k: r[k] for k in ("name", "score", "rank")} for r in board]
    return data


def host_state(session, now=None):
    now = now or timezone.now()
    all_teams = list(session.teams.all())
    teams = [t for t in all_teams if t.status == TeamStatus.ACTIVE]
    data = display_state(session, teams=teams, now=now)
    scores = team_scores(session)
    board = {r["team_id"]: r for r in leaderboard(session, teams=teams, scores=scores)}
    data["leaderboard"] = [{k: r[k] for k in ("name", "score", "rank")} for r in sorted(board.values(), key=lambda r: r["rank"])]

    runtime = runtime_for_session(session)
    subs = {}
    if runtime is not None:
        subs = {s.team_id: s for s in runtime.submissions.all()}
        q = data.get("question")
        if q is not None:
            q["answer_key"] = runtime.question.answer_key
            q["answer_display"] = runtime.question.answer_display
            q["explanation"] = runtime.question.explanation
            q["clarification"] = runtime.question.clarification
            q["question_count"] = runtime.question.mission.questions.count()

    revealed = runtime is not None and runtime.status == RuntimeStatus.REVEALED
    data["team_table"] = [
        {
            "id": t.pk,
            "name": t.name,
            "slot": t.slot,
            "connected": t.is_connected(now),
            "last_seen_s": int((now - t.last_seen).total_seconds()),
            "score": scores.get(t.pk, 0) or 0,
            "rank": board[t.pk]["rank"],
            "submitted": t.pk in subs,
            "correct": (subs[t.pk].is_correct if revealed and t.pk in subs else None),
            "reconnects": t.reconnect_count,
            "recovery_pending": bool(t.recovery_expires_at and t.recovery_expires_at > now),
        }
        for t in sorted(teams, key=lambda t: t.slot)
    ]
    data["removed_teams"] = [{"name": t.name, "slot": t.slot} for t in all_teams if t.status != TeamStatus.ACTIVE]
    data["events"] = [
        {"time": ms(e.created_at), "kind": e.kind, "message": e.message}
        for e in SessionEvent.objects.filter(session=session).order_by("-created_at", "-id")[:40]
    ]
    missions = list(Mission.objects.filter(experience_id=session.experience_id).order_by("order"))
    data["missions"] = [
        {
            "code": m.code,
            "title": m.title,
            "current": m.pk == session.current_mission_id,
            "done": session.current_mission is not None and m.order < session.current_mission.order,
        }
        for m in missions
    ]
    data["speed_bonus_enabled"] = session.speed_bonus_enabled
    data["expires_at"] = ms(session.expires_at)
    data["allowed_actions"] = engine.allowed_actions(session)
    data["current_runtime_id"] = session.current_runtime_id
    return data
