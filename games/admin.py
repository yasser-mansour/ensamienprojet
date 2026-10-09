from django.contrib import admin

from .models import AnswerOption, Experience, Mission, Question


class AnswerOptionInline(admin.TabularInline):
    model = AnswerOption
    extra = 0


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("mission", "order", "kind", "prompt", "source", "points")
    list_filter = ("mission", "kind", "source")
    inlines = [AnswerOptionInline]


@admin.register(Mission)
class MissionAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "default_duration", "is_final")


admin.site.register(Experience)
