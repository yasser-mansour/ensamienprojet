"""
Runtime models for a live ENERGY LAB session.

Invariants enforced by the database (not only by Python code):
  * a join code is unique among sessions that are not FINISHED/ARCHIVED;
  * at most one active team per slot, and slots are numbered 1..MAX_TEAMS;
  * team names are unique per session (case- and whitespace-insensitive);
  * one submission per team per question runtime;
  * automatic question points are awarded at most once per team per question per session,
    even if a mission is restarted;
  * host action request ids are unique per session (idempotent retries).
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from games.models import Experience, Mission, Question

MAX_TEAMS = settings.ENSAMIEN["MAX_TEAMS"]


class SessionStatus(models.TextChoices):
    CREATED = "CREATED", "Created"
    LOBBY = "LOBBY", "Lobby"
    MISSION_INTRO = "MISSION_INTRO", "Mission intro"
    QUESTION_OPEN = "QUESTION_OPEN", "Question open"
    QUESTION_CLOSED = "QUESTION_CLOSED", "Question closed"
    ANSWER_REVEALED = "ANSWER_REVEALED", "Answer revealed"
    LEADERBOARD = "LEADERBOARD", "Leaderboard"
    MISSION_COMPLETE = "MISSION_COMPLETE", "Mission complete"
    PAUSED = "PAUSED", "Paused"
    FINISHED = "FINISHED", "Finished"
    ARCHIVED = "ARCHIVED", "Archived"


CLOSED_STATUSES = (SessionStatus.FINISHED, SessionStatus.ARCHIVED)


class GameSession(models.Model):
    experience = models.ForeignKey(Experience, on_delete=models.PROTECT, related_name="sessions")
    code = models.CharField(max_length=6, db_index=True)
    status = models.CharField(max_length=20, choices=SessionStatus.choices, default=SessionStatus.CREATED)
    paused_from = models.CharField(max_length=20, choices=SessionStatus.choices, blank=True)
    registration_open = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    current_mission = models.ForeignKey(Mission, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    current_runtime = models.ForeignKey(
        "QuestionRuntime", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    speed_bonus_enabled = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=~Q(status__in=["FINISHED", "ARCHIVED"]),
                name="uniq_code_among_open_sessions",
            ),
            models.CheckConstraint(condition=Q(code__regex=r"^[0-9]{6}$"), name="code_six_digits"),
        ]

    def __str__(self):
        return f"Session {self.code} ({self.status})"

    @property
    def is_closed(self):
        return self.status in CLOSED_STATUSES

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def effective_status(self):
        """The underlying game phase, looking through a pause."""
        return self.paused_from if self.status == SessionStatus.PAUSED else self.status


class TeamStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    REMOVED = "REMOVED", "Removed"


class TeamParticipation(models.Model):
    """A team (one captain's phone) inside one session. Teams are never Django users."""

    session = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name="teams")
    slot = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=40)
    name_key = models.CharField(max_length=40, help_text="Normalised name for duplicate detection")
    token_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=10, choices=TeamStatus.choices, default=TeamStatus.ACTIVE)
    joined_at = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)
    removed_at = models.DateTimeField(null=True, blank=True)
    recovery_code_hash = models.CharField(max_length=64, blank=True)
    recovery_expires_at = models.DateTimeField(null=True, blank=True)
    reconnect_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["slot"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "slot"], condition=Q(status="ACTIVE"), name="uniq_active_slot_per_session"
            ),
            models.UniqueConstraint(
                fields=["session", "name_key"], condition=Q(status="ACTIVE"), name="uniq_active_team_name"
            ),
            models.CheckConstraint(condition=Q(slot__gte=1, slot__lte=MAX_TEAMS), name="slot_in_range"),
        ]

    def __str__(self):
        return f"{self.name} (slot {self.slot})"

    @property
    def is_active(self):
        return self.status == TeamStatus.ACTIVE

    def is_connected(self, now=None):
        now = now or timezone.now()
        return (now - self.last_seen).total_seconds() <= settings.ENSAMIEN["PRESENCE_TIMEOUT_SECONDS"]


class RuntimeStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    CLOSED = "CLOSED", "Closed"
    REVEALED = "REVEALED", "Revealed"
    SKIPPED = "SKIPPED", "Skipped"


class QuestionRuntime(models.Model):
    """One play of one question inside a session. Restarting a mission creates a new attempt."""

    session = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name="runtimes")
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="runtimes")
    attempt = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=10, choices=RuntimeStatus.choices, default=RuntimeStatus.OPEN)
    duration_seconds = models.PositiveSmallIntegerField()
    opened_at = models.DateTimeField(default=timezone.now)
    deadline = models.DateTimeField(null=True, blank=True, help_text="Null while the game is paused")
    paused_remaining_ms = models.PositiveIntegerField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    revealed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["opened_at"]
        constraints = [
            models.UniqueConstraint(fields=["session", "question", "attempt"], name="uniq_runtime_attempt"),
        ]

    def __str__(self):
        return f"{self.session.code} · {self.question} · attempt {self.attempt}"

    def remaining_ms(self, now=None):
        if self.deadline is None:
            return self.paused_remaining_ms or 0
        now = now or timezone.now()
        return max(0, int((self.deadline - now).total_seconds() * 1000))


class TeamSubmission(models.Model):
    runtime = models.ForeignKey(QuestionRuntime, on_delete=models.CASCADE, related_name="submissions")
    team = models.ForeignKey(TeamParticipation, on_delete=models.CASCADE, related_name="submissions")
    answer = models.JSONField()
    is_correct = models.BooleanField()
    time_fraction_left = models.FloatField(default=0.0)
    submitted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["submitted_at"]
        constraints = [models.UniqueConstraint(fields=["runtime", "team"], name="uniq_submission_per_runtime")]


class ScoreSource(models.TextChoices):
    QUESTION = "QUESTION", "Question"
    MANUAL = "MANUAL", "Manual adjustment"


class ScoreEvent(models.Model):
    """Append-only score ledger. Leaderboards are always the sum of these rows."""

    session = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name="score_events")
    team = models.ForeignKey(TeamParticipation, on_delete=models.CASCADE, related_name="score_events")
    points = models.IntegerField()
    reason = models.CharField(max_length=160)
    source = models.CharField(max_length=10, choices=ScoreSource.choices)
    question = models.ForeignKey(Question, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    runtime = models.ForeignKey(QuestionRuntime, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "team", "question"],
                condition=Q(source="QUESTION"),
                name="uniq_question_award_per_team",
            ),
            models.CheckConstraint(
                condition=Q(source="MANUAL") | Q(question__isnull=False), name="question_award_has_question"
            ),
        ]


class SessionEvent(models.Model):
    """Audit log of significant actions, shown on the host dashboard and in history."""

    session = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=32)
    message = models.CharField(max_length=255)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    request_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["session", "-created_at"], name="event_session_recent")]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "request_id"], condition=~Q(request_id=""), name="uniq_host_request_id"
            ),
        ]


class DisplayToken(models.Model):
    """Read-only, session-scoped credential for the projector window."""

    session = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name="display_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    revoked = models.BooleanField(default=False)

    def is_valid(self):
        return not self.revoked and timezone.now() < self.expires_at
