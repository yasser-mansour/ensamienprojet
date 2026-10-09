"""
Reusable game content. Sessions (in the `live` app) reference this content but never modify it,
so the same missions can be played by any number of sessions.
"""

from django.db import models


class Experience(models.Model):
    """An interactive experience hosted on ENSAMien (e.g. ENERGY LAB LIVE)."""

    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=80)
    subtitle = models.CharField(max_length=120, blank=True)
    source_reference = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.title


class Mission(models.Model):
    experience = models.ForeignKey(Experience, on_delete=models.CASCADE, related_name="missions")
    order = models.PositiveSmallIntegerField()
    code = models.CharField(max_length=4, help_text="Display number, e.g. 01")
    slug = models.SlugField()
    title = models.CharField(max_length=80)
    objective = models.CharField(max_length=255)
    briefing = models.TextField(blank=True)
    default_duration = models.PositiveSmallIntegerField(help_text="Seconds per question")
    is_final = models.BooleanField(default=False)

    class Meta:
        ordering = ["experience", "order"]
        constraints = [
            models.UniqueConstraint(fields=["experience", "order"], name="uniq_mission_order"),
            models.UniqueConstraint(fields=["experience", "slug"], name="uniq_mission_slug"),
        ]

    def __str__(self):
        return f"Mission {self.code} — {self.title}"


class Question(models.Model):
    class Kind(models.TextChoices):
        SINGLE = "SINGLE", "Single choice"
        TRUE_FALSE = "TRUE_FALSE", "True / false"
        MATCH = "MATCH", "Matching"
        ORDER = "ORDER", "Sequence ordering"

    class Source(models.TextChoices):
        TEXTBOOK = "TEXTBOOK", "Textbook"
        SUPPLEMENTARY = "SUPPLEMENTARY", "Supplementary"

    mission = models.ForeignKey(Mission, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=12, choices=Kind.choices)
    label = models.CharField(max_length=40, blank=True, help_text="e.g. SITUATION 1 / 5")
    prompt = models.CharField(max_length=300)
    context = models.CharField(max_length=300, blank=True, help_text="Scenario or quoted sentence")
    # MATCH only: the left-hand terms, [{"key": "1", "text": "abstract"}, ...]
    items = models.JSONField(default=list, blank=True)
    # Server-only answer key. SINGLE/TRUE_FALSE: "B"; MATCH: {"1": "A", ...}; ORDER: ["B", "D", "A", "C"]
    answer_key = models.JSONField()
    answer_display = models.CharField(max_length=200, help_text="Correct answer shown at reveal")
    explanation = models.TextField()
    clarification = models.TextField(
        blank=True, help_text="Supplementary science note shown separately from the textbook wording"
    )
    source = models.CharField(max_length=14, choices=Source.choices)
    source_reference = models.CharField(max_length=160)
    points = models.PositiveSmallIntegerField(default=100)
    duration = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Overrides mission default")

    class Meta:
        ordering = ["mission", "order"]
        constraints = [models.UniqueConstraint(fields=["mission", "order"], name="uniq_question_order")]

    def __str__(self):
        return f"{self.mission.code}.{self.order} {self.prompt[:50]}"

    @property
    def effective_duration(self):
        return self.duration or self.mission.default_duration


class AnswerOption(models.Model):
    """A selectable choice: a multiple-choice option, a matching definition, or a sequence card."""

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    key = models.CharField(max_length=4)
    text = models.CharField(max_length=200)
    order = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["question", "order"]
        constraints = [models.UniqueConstraint(fields=["question", "key"], name="uniq_option_key")]

    def __str__(self):
        return f"{self.key}: {self.text}"
