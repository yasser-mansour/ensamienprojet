"""
Business logic for sessions, teams and submissions. Views stay thin and call these functions.
Host-driven state transitions live in `live.engine`.
"""

import re
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from games.models import Experience

from . import grading, tokens
from .models import (
    CLOSED_STATUSES,
    MAX_TEAMS,
    GameSession,
    QuestionRuntime,
    ScoreEvent,
    SessionEvent,
    SessionStatus,
    TeamParticipation,
    TeamStatus,
    TeamSubmission,
)

CONF = settings.ENSAMIEN


class ServiceError(Exception):
    """An expected, user-facing failure. `code` is machine-readable, `message` is shown to people."""

    status = 400

    def __init__(self, code, message, status=None):
        super().__init__(message)
        self.code = code
        self.message = message
        if status is not None:
            self.status = status


JOIN_MESSAGES = {
    "INVALID_CODE": "INVALID SESSION CODE",
    "EXPIRED": "SESSION EXPIRED",
    "REGISTRATION_CLOSED": "REGISTRATION CLOSED",
    "FULL": "SESSION FULL",
    "NAME_TAKEN": "TEAM NAME ALREADY TAKEN",
    "NAME_INVALID": "INVALID TEAM NAME",
    "INVALID_RECOVERY": "INVALID OR EXPIRED RECOVERY CODE",
}


def join_error(code, status=400):
    return ServiceError(code, JOIN_MESSAGES[code], status)


def bump_version(session):
    """Increment the polling version. Caller must hold the session row lock."""
    session.version += 1
    session.save(update_fields=["version"])


def log_event(session, kind, message, actor=None, request_id=""):
    return SessionEvent.objects.create(
        session=session, kind=kind, message=message[:255], actor=actor, request_id=request_id or ""
    )


# --- Sessions -------------------------------------------------------------


def default_experience():
    return Experience.objects.get(slug="energy-lab")


def create_session(user, experience=None):
    experience = experience or default_experience()
    now = timezone.now()
    for _ in range(25):
        code = tokens.new_join_code()
        if GameSession.objects.filter(code=code).exclude(status__in=CLOSED_STATUSES).exists():
            continue
        try:
            with transaction.atomic():
                session = GameSession.objects.create(
                    experience=experience,
                    code=code,
                    status=SessionStatus.CREATED,
                    registration_open=True,
                    created_by=user,
                    created_at=now,
                    expires_at=now + timedelta(hours=CONF["SESSION_LIFETIME_HOURS"]),
                    speed_bonus_enabled=CONF["SPEED_BONUS_ENABLED"],
                )
                # CREATED -> LOBBY once the initial state is in place (slots are implicit: 1..MAX_TEAMS).
                session.status = SessionStatus.LOBBY
                session.save(update_fields=["status"])
                log_event(session, "create_session", f"Session {code} created · registration open", actor=user)
            return session
        except IntegrityError:  # a concurrent creation took the same code
            continue
    raise ServiceError("CODE_GENERATION_FAILED", "Could not allocate a session code. Try again.", 503)


def create_display_token(session):
    raw, digest = tokens.new_token()
    from .models import DisplayToken

    DisplayToken.objects.create(
        session=session,
        token_hash=digest,
        expires_at=timezone.now() + timedelta(hours=CONF["DISPLAY_TOKEN_HOURS"]),
    )
    return raw


def session_for_display_token(raw):
    from .models import DisplayToken

    token = DisplayToken.objects.select_related("session").filter(token_hash=tokens.hash_token(raw or "")).first()
    if token is None or not token.is_valid():
        return None
    return token.session


# --- Joining --------------------------------------------------------------

_CODE_RE = re.compile(r"^[0-9]{6}$")
_SPACE_RE = re.compile(r"\s+")


def normalize_code(raw):
    code = re.sub(r"\D", "", raw or "")
    return code if _CODE_RE.match(code) else None


def find_joinable_session(raw_code):
    """Validate a join code. Ended sessions are reported as invalid so old codes reveal nothing."""
    code = normalize_code(raw_code)
    if code is None:
        raise join_error("INVALID_CODE")
    session = GameSession.objects.filter(code=code).exclude(status__in=CLOSED_STATUSES).first()
    if session is None:
        raise join_error("INVALID_CODE")
    if session.is_expired:
        raise join_error("EXPIRED", 410)
    if not session.registration_open:
        raise join_error("REGISTRATION_CLOSED", 403)
    if session.teams.filter(status=TeamStatus.ACTIVE).count() >= MAX_TEAMS:
        raise join_error("FULL", 409)
    return session


def clean_team_name(raw):
    """Return (display_name, name_key). Rejects empty, over-long and non-printable names."""
    name = unicodedata.normalize("NFKC", raw or "")
    name = _SPACE_RE.sub(" ", name).strip()
    if not name:
        raise ServiceError("NAME_INVALID", "ENTER A TEAM NAME")
    if len(name) > CONF["TEAM_NAME_MAX_LENGTH"]:
        raise ServiceError("NAME_INVALID", f"TEAM NAME TOO LONG (MAX {CONF['TEAM_NAME_MAX_LENGTH']} CHARACTERS)")
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Co", "Cs") for ch in name):
        raise ServiceError("NAME_INVALID", "TEAM NAME CONTAINS INVALID CHARACTERS")
    if "<" in name or ">" in name:
        raise ServiceError("NAME_INVALID", "TEAM NAME CANNOT CONTAIN < OR >")
    return name, name.casefold()


def join_team(session_id, raw_name):
    """
    Atomically allocate a free slot to a new team. The session row is locked so concurrent
    joins are serialised; the partial unique constraints are a second line of defence.
    Returns (team, raw_token). The raw token is only given to the joining device.
    """
    name, name_key = clean_team_name(raw_name)
    for _attempt in range(4):
        try:
            with transaction.atomic():
                session = GameSession.objects.select_for_update().get(pk=session_id)
                if session.is_closed:
                    raise join_error("INVALID_CODE")
                if session.is_expired:
                    raise join_error("EXPIRED", 410)
                if not session.registration_open:
                    raise join_error("REGISTRATION_CLOSED", 403)
                active = list(session.teams.filter(status=TeamStatus.ACTIVE).values_list("slot", "name_key"))
                if any(key == name_key for _slot, key in active):
                    raise join_error("NAME_TAKEN", 409)
                taken = {slot for slot, _key in active}
                free = [slot for slot in range(1, MAX_TEAMS + 1) if slot not in taken]
                if not free:
                    raise join_error("FULL", 409)
                raw_token, digest = tokens.new_token()
                now = timezone.now()
                team = TeamParticipation.objects.create(
                    session=session,
                    slot=free[0],
                    name=name,
                    name_key=name_key,
                    token_hash=digest,
                    joined_at=now,
                    last_seen=now,
                )
                bump_version(session)
                log_event(session, "team_joined", f"{name} joined (slot {team.slot})")
                return team, raw_token
        except IntegrityError:
            # Lost a race on SQLite (no row locks) — re-read and try again.
            continue
    raise ServiceError("JOIN_CONFLICT", "PLEASE TRY AGAIN", 409)


def authenticate_team(raw_token):
    if not raw_token or len(raw_token) > 128:
        return None
    return (
        TeamParticipation.objects.select_related("session")
        .filter(token_hash=tokens.hash_token(raw_token))
        .first()
    )


def touch_presence(team, now=None):
    """Record that the team's device is alive. Writes at most every few seconds per team."""
    now = now or timezone.now()
    if (now - team.last_seen).total_seconds() >= CONF["PRESENCE_WRITE_INTERVAL_SECONDS"]:
        TeamParticipation.objects.filter(pk=team.pk).update(last_seen=now)
        team.last_seen = now


def issue_recovery_code(team):
    """Host-only: a one-time code that lets a new device take over this team."""
    code = tokens.new_recovery_code()
    team.recovery_code_hash = tokens.hash_token(code)
    team.recovery_expires_at = timezone.now() + timedelta(minutes=CONF["RECOVERY_CODE_MINUTES"])
    team.save(update_fields=["recovery_code_hash", "recovery_expires_at"])
    return code


def recover_team(session_id, raw_code):
    """
    Exchange a host-issued recovery code for a fresh team credential. Knowing a team's
    name is not enough; the old device's credential stops working immediately.
    """
    code = re.sub(r"[^A-Za-z0-9]", "", raw_code or "").upper()
    if len(code) != 6:
        raise join_error("INVALID_RECOVERY")
    with transaction.atomic():
        session = GameSession.objects.select_for_update().get(pk=session_id)
        team = (
            session.teams.select_for_update()
            .filter(status=TeamStatus.ACTIVE, recovery_code_hash=tokens.hash_token(code))
            .first()
        )
        if team is None or session.is_closed or not team.recovery_expires_at or team.recovery_expires_at < timezone.now():
            raise join_error("INVALID_RECOVERY")
        raw_token, digest = tokens.new_token()
        team.token_hash = digest
        team.recovery_code_hash = ""
        team.recovery_expires_at = None
        team.reconnect_count += 1
        team.last_seen = timezone.now()
        team.save(update_fields=["token_hash", "recovery_code_hash", "recovery_expires_at", "reconnect_count", "last_seen"])
        bump_version(session)
        log_event(session, "team_recovered", f"{team.name} reconnected on a new device")
        return team, raw_token


# --- Submissions ----------------------------------------------------------


def submit_answer(team, runtime_id, answer):
    """
    Accept one answer per team per question runtime. Everything is validated server-side:
    session phase, active question, deadline (server clock), format and duplicates.
    Returns (submission, created). Re-sending the same answer is idempotent.
    """
    with transaction.atomic():
        # Locking the session row orders this submission strictly before or after any host
        # close/reveal, so nothing can slip in after a question is closed.
        session = GameSession.objects.select_for_update().get(pk=team.session_id)
        now = timezone.now()
        team = TeamParticipation.objects.get(pk=team.pk)
        if team.status != TeamStatus.ACTIVE:
            raise ServiceError("TEAM_REMOVED", "YOUR TEAM WAS REMOVED BY THE HOST", 403)
        if session.status == SessionStatus.PAUSED:
            raise ServiceError("PAUSED", "GAME PAUSED — WAIT FOR THE HOST", 409)
        runtime = session.current_runtime
        if runtime is None or str(runtime.pk) != str(runtime_id):
            raise ServiceError("STALE_QUESTION", "THIS QUESTION IS NO LONGER ACTIVE", 409)

        existing = TeamSubmission.objects.filter(runtime=runtime, team=team).first()
        question = runtime.question
        option_keys = list(question.options.values_list("key", flat=True))
        normalized = grading.normalize_answer(question, option_keys, answer)
        if existing is not None:
            if existing.answer == normalized:
                return existing, False
            raise ServiceError("ALREADY_ANSWERED", "YOUR TEAM HAS ALREADY ANSWERED", 409)

        if session.status != SessionStatus.QUESTION_OPEN or runtime.status != "OPEN":
            raise ServiceError("QUESTION_CLOSED", "ANSWERS ARE CLOSED", 409)
        grace = timedelta(seconds=CONF["SUBMISSION_GRACE_SECONDS"])
        if runtime.deadline is None or now > runtime.deadline + grace:
            raise ServiceError("TIME_UP", "TIME IS UP", 409)

        fraction = max(0.0, min(1.0, runtime.remaining_ms(now) / (runtime.duration_seconds * 1000)))
        submission = TeamSubmission.objects.create(
            runtime=runtime,
            team=team,
            answer=normalized,
            is_correct=grading.is_correct(question, normalized),
            time_fraction_left=fraction,
            submitted_at=now,
        )
        bump_version(session)
        return submission, True


# --- Scores ---------------------------------------------------------------


def team_scores(session):
    return dict(
        ScoreEvent.objects.filter(session=session).values_list("team").annotate(total=Sum("points")).values_list(
            "team", "total"
        )
    )


def leaderboard(session, teams=None, scores=None):
    """Ranked active teams. Equal scores share a rank (1, 1, 3 …); ties are listed alphabetically."""
    if teams is None:
        teams = list(session.teams.filter(status=TeamStatus.ACTIVE))
    scores = team_scores(session) if scores is None else scores
    rows = sorted(
        ({"team_id": t.pk, "name": t.name, "slot": t.slot, "score": scores.get(t.pk, 0) or 0} for t in teams),
        key=lambda r: (-r["score"], r["name"].casefold()),
    )
    for row in rows:
        row["rank"] = 1 + sum(1 for other in rows if other["score"] > row["score"])
    return rows


def award_runtime(session, runtime):
    """Create score events for every correct, active submission. Safe to call more than once."""
    question = runtime.question
    awarded = 0
    submissions = runtime.submissions.select_related("team").filter(is_correct=True, team__status=TeamStatus.ACTIVE)
    for sub in submissions:
        points = question.points
        if session.speed_bonus_enabled:
            points += round(CONF["SPEED_BONUS_MAX"] * sub.time_fraction_left)
        if ScoreEvent.objects.filter(session=session, team=sub.team, question=question, source="QUESTION").exists():
            continue  # already awarded in an earlier attempt of this mission
        try:
            with transaction.atomic():
                ScoreEvent.objects.create(
                    session=session,
                    team=sub.team,
                    points=points,
                    reason=f"Mission {question.mission.code} · {question.label or question.prompt}"[:160],
                    source="QUESTION",
                    question=question,
                    runtime=runtime,
                )
                awarded += 1
        except IntegrityError:
            continue
    return awarded


def presence_signature(teams, now=None):
    now = now or timezone.now()
    return ",".join(f"{t.pk}{'c' if t.is_connected(now) else 'd'}" for t in teams)


def runtime_for_session(session):
    if session.current_runtime_id is None:
        return None
    return QuestionRuntime.objects.select_related("question", "question__mission").get(pk=session.current_runtime_id)
