from django import forms
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from . import ratelimit

GENERIC_ERROR = "Incorrect e-mail or password."
LOCKED_ERROR = "Too many sign-in attempts. Please wait a few minutes and try again."


class HostLoginForm(forms.Form):
    email = forms.EmailField(max_length=254)
    password = forms.CharField(max_length=256, strip=False, widget=forms.PasswordInput)


@sensitive_post_parameters("password")
@csrf_protect
@never_cache
def login_view(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect(settings.LOGIN_REDIRECT_URL)

    limits = settings.ENSAMIEN
    form = HostLoginForm(request.POST or None)
    error = None
    next_url = request.POST.get("next") or request.GET.get("next") or ""

    if request.method == "POST":
        ip = ratelimit.client_ip(request)
        email = (request.POST.get("email") or "").strip().lower()
        if ratelimit.is_limited("login-ip", ip, limits["LOGIN_LIMIT_PER_IP"]) or ratelimit.is_limited(
            "login-acct", email, limits["LOGIN_LIMIT_PER_ACCOUNT"]
        ):
            error = LOCKED_ERROR
        elif form.is_valid():
            user = authenticate(request, email=form.cleaned_data["email"], password=form.cleaned_data["password"])
            if user is not None:
                ratelimit.reset("login-acct", email)
                login(request, user)
                if next_url and url_has_allowed_host_and_scheme(
                    next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
                ):
                    return redirect(next_url)
                return redirect(settings.LOGIN_REDIRECT_URL)
            error = GENERIC_ERROR
        else:
            error = GENERIC_ERROR
        if error == GENERIC_ERROR:
            ratelimit.register_failure("login-ip", ip, limits["LOGIN_LIMIT_PER_IP"])
            ratelimit.register_failure("login-acct", email, limits["LOGIN_LIMIT_PER_ACCOUNT"])

    status = 200 if error is None else (429 if error == LOCKED_ERROR else 401)
    return render(
        request,
        "accounts/login.html",
        {"form": form, "error": error, "next": next_url},
        status=status,
    )


@require_POST
def logout_view(request):
    logout(request)
    return redirect("accounts:login")
