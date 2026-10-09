"""
The host-controlled game state machine.

Every host action goes through `perform()`, which:
  1. locks the session row (serialising concurrent host clicks, submissions and joins);
  2. drops exact retries (same request_id) without re-applying them;
  3. rejects stale clicks (`expected_status` / `expected_runtime` no longer match), so a
     double-click or two open dashboards can never advance the game twice;
  4. checks the action is legal from the current state (ACTION_STATES);
  5. applies the transition, bumps the polling version and writes an audit event.

State diagram (main path):

    LOBBY ─start_game→ MISSION_INTRO ─start_question→ QUESTION_OPEN ─close_question→ QUESTION_CLOSED
    QUESTION_CLOSED ─reveal_answer→ ANSWER_REVEALED ─show_leaderboard→ LEADERBOARD
    ANSWER_REVEALED / LEADERBOARD ─next_question→ QUESTION_OPEN (next) | MISSION_COMPLETE (last)
    MISSION_COMPLETE ─next_mission→ MISSION_INTRO (next mission)
    any active state ─pause→ PAUSED ─resume→ previous state
    any open state ─finish_game→ FINISHED ─archive→ ARCHIVED
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from games.models import Mission

from .models import (
    GameSession,
    QuestionRuntime,
    RuntimeStatus,
    ScoreEvent,
    SessionEvent,
    SessionStatus as S,
    TeamParticipation,
    TeamStatus,
)
from .services import ServiceError, award_runtime, issue_recovery_code

ACTIVE_PLAY = {S.MISSION_INTRO, S.QUESTION_OPEN, S.QUESTION_CLOSED, S.ANSWER_REVEALED, S.LEADERBOARD, S.MISSION_COMPLETE}
NOT_CLOSED = {S.CREATED, S.LOBBY, S.PAUSED} | ACTIVE_PLAY

# Legal source states for each action.
ACTION_STATES = {
    "start_game": {S.LOBBY},
    "start_question": {S.MISSION_INTRO},
    "close_question": {S.QUESTION_OPEN},
    "reopen_question": {S.QUESTION_CLOSED},
    "extend_time": {S.QUESTION_OPEN},
    "reveal_answer": {S.QUESTION_CLOSED},
    "show_leaderboard": {S.ANSWER_REVEALED, S.MISSION_COMPLETE},
    "next_question": {S.ANSWER_REVEALED, S.LEADERBOARD},
    "skip_question": {S.QUESTION_OPEN, S.QUESTION_CLOSED},
    "next_mission": {S.MISSION_INTRO, S.ANSWER_REVEALED, S.LEADERBOARD, S.MISSION_COMPLETE},
    "restart_mission": {S.MISSION_INTRO, S.QUESTION_CLOSED, S.ANSWER_REVEALED, S.LEADERBOARD, S.MISSION_COMPLETE},
    "pause": {S.LOBBY} | ACTIVE_PLAY,
    "resume": {S.PAUSED},
    "open_registration": NOT_CLOSED,
    "close_registration": NOT_CLOSED,
    "toggle_speed_bonus": NOT_CLOSED,
    "finish_game": NOT_CLOSED,
    "archive": {S.FINISHED},
    # Team management is allowed while the session is open, and score corrections afterwards too.
    "remove_team": NOT_CLOSED,
    "issue_recovery": NOT_CLOSED,
    "adjust_score": NOT_CLOSED | {S.FINISHED},
}

ACTION_LABELS = {
    "start_game": "start the game",
    "start_question": "start the question",
    "close_question": "close the question",
    "reopen_question": "reopen the question",
    "extend_time": "extend the time",
    "reveal_answer": "reveal the answer",
    "show_leaderboard": "show the leaderboard",
    "next_question": "go to the next question",
    "skip_question": "skip the question",
    "next_mission": "go to the next mission",
    "restart_mission": "restart the mission",
    "pause": "pause",
    "resume": "resume",
    "finish_game": "finish the game",
    "archive": "archive the session",
}


class ActionError(ServiceError):
    status = 409


# --- helpers --------------------------------------------------------------


def _missions(session):
    return list(Mission.objects.filter(experience_id=session.experience_id).order_by("order"))


def _questions(mission):
    return list(mission.questions.order_by("order"))


def _next_question(session, runtime):
    questions = _questions(session.current_mission)
    if runtime is None:
        return questions[0] if questions else None
    later = [q for q in questions if q.order > runtime.question.order]
    return later[0] if later else None


def _next_mission(session):
    missions = _missions(session)
    if session.current_mission_id is None:
        return missions[0] if missions else None
    later = [m for m in missions if m.order > session.current_mission.order]
    return later[0] if later else None


def _open_question(session, question, now):
    attempt = QuestionRuntime.objects.filter(session=session, question=question).count() + 1
    duration = question.effective_duration
    runtime = QuestionRuntime.objects.create(
        session=session,
        question=question,
        attempt=attempt,
        status=RuntimeStatus.OPEN,
        duration_seconds=duration,
        opened_at=now,
        deadline=now + timedelta(seconds=duration),
    )
    session.current_runtime = runtime
    session.status = S.QUESTION_OPEN
    label = question.label or f"Q{question.order}"
    suffix = f" (attempt {attempt})" if attempt > 1 else ""
    return f"Mission {question.mission.code} · {label} opened{suffix} · {duration}s"


def _void_unrevealed(runtime, now):
    """Close a question that will not be revealed. It never awards points."""
    if runtime is not None and runtime.status in (RuntimeStatus.OPEN, RuntimeStatus.CLOSED):
        runtime.status = RuntimeStatus.SKIPPED
        runtime.closed_at = runtime.closed_at or now
        runtime.save(update_fields=["status", "closed_at"])


def _advance_after(session, runtime, now):
    nxt = _next_question(session, runtime)
    if nxt is not None:
        return _open_question(session, nxt, now)
    session.status = S.MISSION_COMPLETE
    return f"Mission {session.current_mission.code} complete"


def _team(session, params):
    try:
        team_id = int(params.get("team_id"))
    except (TypeError, ValueError):
        raise ActionError("BAD_TEAM", "Select a team.", 400)
    team = TeamParticipation.objects.filter(session=session, pk=team_id, status=TeamStatus.ACTIVE).first()
    if team is None:
        raise ActionError("BAD_TEAM", "That team is no longer in the session.", 404)
    return team


def _int_param(params, name, default, low, high):
    try:
        value = int(params.get(name, default))
    except (TypeError, ValueError):
        raise ActionError("BAD_PARAM", f"Invalid {name}.", 400)
    if not low <= value <= high:
        raise ActionError("BAD_PARAM", f"{name} must be between {low} and {high}.", 400)
    return value


# --- handlers: each returns (log message, extra result dict) ---------------


def h_start_game(session, user, params, rt, now):
    if not session.teams.filter(status=TeamStatus.ACTIVE).exists():
        raise ActionError("NO_TEAMS", "At least one team must join before the game can start.")
    mission = _next_mission(session)
    if mission is None:
        raise ActionError("NO_CONTENT", "No missions are loaded. Run `manage.py seed_energy_lab`.")
    session.registration_open = False
    session.current_mission = mission
    session.current_runtime = None
    session.status = S.MISSION_INTRO
    session.started_at = session.started_at or now
    return f"Game started · registration closed · Mission {mission.code} {mission.title}", {}


def h_start_question(session, user, params, rt, now):
    question = _next_question(session, None)
    if question is None:
        raise ActionError("NO_QUESTIONS", "This mission has no questions.")
    return _open_question(session, question, now), {}


def h_close_question(session, user, params, rt, now):
    rt.status = RuntimeStatus.CLOSED
    rt.closed_at = now
    rt.save(update_fields=["status", "closed_at"])
    session.status = S.QUESTION_CLOSED
    return f"Question closed · {rt.submissions.count()} answers received", {}


def h_reopen_question(session, user, params, rt, now):
    seconds = _int_param(params, "seconds", 15, 5, 300)
    rt.status = RuntimeStatus.OPEN
    rt.closed_at = None
    rt.deadline = now + timedelta(seconds=seconds)
    rt.duration_seconds = max(rt.duration_seconds, seconds)
    rt.save(update_fields=["status", "closed_at", "deadline", "duration_seconds"])
    session.status = S.QUESTION_OPEN
    return f"Question reopened · +{seconds}s", {}


def h_extend_time(session, user, params, rt, now):
    seconds = _int_param(params, "seconds", 15, 5, 120)
    rt.deadline = max(rt.deadline, now) + timedelta(seconds=seconds)
    rt.duration_seconds = max(rt.duration_seconds, int((rt.deadline - now).total_seconds()) + 1)
    rt.save(update_fields=["deadline", "duration_seconds"])
    return f"Time extended by {seconds}s", {}


def h_reveal_answer(session, user, params, rt, now):
    rt.status = RuntimeStatus.REVEALED
    rt.revealed_at = now
    rt.save(update_fields=["status", "revealed_at"])
    awarded = award_runtime(session, rt)
    session.status = S.ANSWER_REVEALED
    return f"Answer revealed · {awarded} team(s) scored", {"awarded": awarded}


def h_show_leaderboard(session, user, params, rt, now):
    session.status = S.LEADERBOARD
    return "Leaderboard displayed", {}


def h_next_question(session, user, params, rt, now):
    return _advance_after(session, rt, now), {}


def h_skip_question(session, user, params, rt, now):
    _void_unrevealed(rt, now)
    return "Question skipped (no points) · " + _advance_after(session, rt, now), {}


def h_next_mission(session, user, params, rt, now):
    mission = _next_mission(session)
    if mission is None:
        raise ActionError("NO_MORE_MISSIONS", "That was the final mission — use FINISH GAME.")
    _void_unrevealed(rt, now)
    session.current_mission = mission
    session.current_runtime = None
    session.status = S.MISSION_INTRO
    return f"Mission {mission.code} {mission.title}", {}


def h_restart_mission(session, user, params, rt, now):
    _void_unrevealed(rt, now)
    session.current_runtime = None
    session.status = S.MISSION_INTRO
    return (
        f"Mission {session.current_mission.code} restarted · questions already scored will not award points twice",
        {},
    )


def h_pause(session, user, params, rt, now):
    if session.status == S.QUESTION_OPEN and rt is not None:
        rt.paused_remaining_ms = rt.remaining_ms(now)
        rt.deadline = None
        rt.save(update_fields=["paused_remaining_ms", "deadline"])
    session.paused_from = session.status
    session.status = S.PAUSED
    return "Game paused", {}


def h_resume(session, user, params, rt, now):
    previous = session.paused_from or S.LOBBY
    if previous == S.QUESTION_OPEN and rt is not None:
        rt.deadline = now + timedelta(milliseconds=rt.paused_remaining_ms or 0)
        rt.paused_remaining_ms = None
        rt.save(update_fields=["deadline", "paused_remaining_ms"])
    session.status = previous
    session.paused_from = ""
    return "Game resumed", {}


def h_open_registration(session, user, params, rt, now):
    session.registration_open = True
    return "Registration opened", {}


def h_close_registration(session, user, params, rt, now):
    session.registration_open = False
    return "Registration closed", {}


def h_toggle_speed_bonus(session, user, params, rt, now):
    session.speed_bonus_enabled = not session.speed_bonus_enabled
    return f"Speed bonus {'enabled' if session.speed_bonus_enabled else 'disabled'}", {}


def h_finish_game(session, user, params, rt, now):
    _void_unrevealed(rt, now)
    if rt is not None and rt.status == RuntimeStatus.SKIPPED:
        session.current_runtime = None
    session.status = S.FINISHED
    session.paused_from = ""
    session.registration_open = False
    session.finished_at = now
    return "Session finished", {}


def h_archive(session, user, params, rt, now):
    session.status = S.ARCHIVED
    return "Session archived", {}


def h_remove_team(session, user, params, rt, now):
    team = _team(session, params)
    team.status = TeamStatus.REMOVED
    team.removed_at = now
    team.recovery_code_hash = ""
    team.save(update_fields=["status", "removed_at", "recovery_code_hash"])
    return f"{team.name} removed · slot {team.slot} reopened", {}


def h_issue_recovery(session, user, params, rt, now):
    team = _team(session, params)
    code = issue_recovery_code(team)
    return f"Recovery code issued for {team.name}", {"recovery_code": code, "team": team.name}


def h_adjust_score(session, user, params, rt, now):
    team = _team(session, params)
    points = _int_param(params, "points", 0, -1000, 1000)
    if points == 0:
        raise ActionError("BAD_PARAM", "Enter a non-zero number of points.", 400)
    reason = str(params.get("reason") or "").strip()[:120]
    if not reason:
        raise ActionError("BAD_PARAM", "A reason is required for manual score changes.", 400)
    ScoreEvent.objects.create(
        session=session, team=team, points=points, reason=reason, source="MANUAL", created_by=user, created_at=now
    )
    return f"{team.name} {points:+d} EP · {reason}", {}


HANDLERS = {name[2:]: fn for name, fn in globals().items() if name.startswith("h_")}
assert set(HANDLERS) == set(ACTION_STATES), "every action needs a handler and a state table entry"

# Actions that move the game forward must carry the state the host saw when clicking.
GUARDED_ACTIONS = set(ACTION_STATES) - {
    "open_registration",
    "close_registration",
    "toggle_speed_bonus",
    "remove_team",
    "issue_recovery",
    "adjust_score",
}


def perform(session_id, user, action, params=None, request_id="", expected_status=None, expected_runtime="__any__"):
    params = params or {}
    handler = HANDLERS.get(action)
    if handler is None:
        raise ActionError("UNKNOWN_ACTION", "Unknown action.", 400)
    request_id = (request_id or "")[:64]
    with transaction.atomic():
        session = (
            GameSession.objects.select_for_update(of=("self",))
            .select_related("current_mission")
            .get(pk=session_id)
        )
        now = timezone.now()  # taken under the lock so event times follow the serialised order
        if request_id and SessionEvent.objects.filter(session=session, request_id=request_id).exists():
            return {"duplicate": True, "message": "Already applied", "version": session.version}
        if action in GUARDED_ACTIONS:
            if expected_status is None:
                raise ActionError("MISSING_STATE", "Missing expected state.", 400)
            stale = expected_status != session.status
            if expected_runtime != "__any__":
                stale = stale or (expected_runtime or None) != (session.current_runtime_id or None)
            if stale:
                raise ActionError("STALE", "The game moved on — the dashboard has been refreshed.")
        if session.status not in ACTION_STATES[action]:
            label = ACTION_LABELS.get(action, action.replace("_", " "))
            current = S(session.status).label.upper()
            raise ActionError("INVALID_TRANSITION", f"Cannot {label} while the session is {current}.")

        rt = None
        if session.current_runtime_id:
            rt = QuestionRuntime.objects.select_for_update(of=("self",)).select_related("question__mission").get(
                pk=session.current_runtime_id
            )
        message, extra = handler(session, user, params, rt, now)
        session.version += 1
        session.save()
        SessionEvent.objects.create(
            session=session, kind=action, message=message[:255], actor=user, request_id=request_id, created_at=now
        )
    return {"duplicate": False, "message": message, "version": session.version, **extra}


def allowed_actions(session):
    """Actions the dashboard should enable right now (same tables the engine enforces)."""
    allowed = {action for action, states in ACTION_STATES.items() if session.status in states}
    if "start_game" in allowed and not session.teams.filter(status=TeamStatus.ACTIVE).exists():
        allowed.discard("start_game")
    if "next_mission" in allowed and _next_mission(session) is None:
        allowed.discard("next_mission")
    return sorted(allowed)
