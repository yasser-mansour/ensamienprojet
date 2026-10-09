from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse

from .services import authenticate_team

TEAM_COOKIE = settings.ENSAMIEN["TEAM_COOKIE_NAME"]


def is_host(user):
    return user.is_authenticated and user.is_active and user.is_staff


def host_required(view):
    """Host-only HTML page: anonymous users are sent to the login screen."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not is_host(request.user):
            return redirect_to_login(request.get_full_path())
        return view(request, *args, **kwargs)

    return wrapper


def host_api(view):
    """Host-only JSON endpoint: never redirects, always answers 403 JSON."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not is_host(request.user):
            return JsonResponse(
                {"ok": False, "error": {"code": "FORBIDDEN", "message": "Host sign-in required."}}, status=403
            )
        return view(request, *args, **kwargs)

    return wrapper


def current_team(request):
    return authenticate_team(request.COOKIES.get(TEAM_COOKIE))


def set_team_cookie(response, raw_token, secure):
    response.set_cookie(
        TEAM_COOKIE,
        raw_token,
        max_age=settings.SESSION_COOKIE_AGE,
        httponly=True,
        secure=secure,
        samesite="Lax",
    )
    return response
