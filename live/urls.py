from django.urls import path

from . import api, views

app_name = "live"

urlpatterns = [
    # Public / team
    path("", views.home, name="home"),
    path("join/team/", views.join_team, name="join_team"),
    path("join/recover/", views.join_recover, name="join_recover"),
    path("play/", views.play, name="play"),
    path("play/leave/", views.leave, name="leave"),
    path("api/live/state/", api.team_state, name="api_team_state"),
    path("api/live/submit/", api.team_submit, name="api_team_submit"),
    # Host
    path("host/", views.host_dashboard, name="host_dashboard"),
    path("host/sessions/new/", views.host_create_session, name="host_create_session"),
    path("host/sessions/<int:session_id>/", views.host_control, name="host_control"),
    path("host/sessions/<int:session_id>/display/", views.host_open_display, name="host_open_display"),
    path("host/sessions/<int:session_id>/report/", views.host_report, name="host_report"),
    path("host/history/", views.host_history, name="host_history"),
    path("api/host/sessions/<int:session_id>/state/", api.host_state, name="api_host_state"),
    path("api/host/sessions/<int:session_id>/action/", api.host_action, name="api_host_action"),
    # Projector (scoped, read-only token)
    path("display/<str:token>/", views.display, name="display"),
    path("api/display/<str:token>/state/", api.display_state, name="api_display_state"),
]
