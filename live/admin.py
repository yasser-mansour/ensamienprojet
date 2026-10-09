from django.contrib import admin

from .models import GameSession, QuestionRuntime, ScoreEvent, SessionEvent, TeamParticipation, TeamSubmission


class TeamInline(admin.TabularInline):
    model = TeamParticipation
    extra = 0
    fields = ("slot", "name", "status", "joined_at", "last_seen")
    readonly_fields = fields


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = ("code", "status", "registration_open", "created_at", "finished_at")
    list_filter = ("status",)
    readonly_fields = ("version",)
    inlines = [TeamInline]


@admin.register(ScoreEvent)
class ScoreEventAdmin(admin.ModelAdmin):
    list_display = ("session", "team", "points", "source", "reason", "created_at")
    list_filter = ("source",)


admin.site.register(QuestionRuntime)
admin.site.register(TeamSubmission)
admin.site.register(SessionEvent)
