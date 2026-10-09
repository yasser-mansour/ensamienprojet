"""
ENSAMien — Django settings.

All deployment-specific values come from environment variables (see .env.example).
The defaults are safe for local development only; production requires
DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS and DATABASE_URL to be set explicitly.
"""

from pathlib import Path
import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

try:  # Optional .env loading for local development.
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover
    pass


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "insecure-development-only-key-never-use-in-production"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Public URL shown on the projector and encoded in the QR code.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "accounts",
    "games",
    "live",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database: DATABASE_URL (PostgreSQL in production). Falls back to SQLite for development.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=int(os.environ.get("DB_CONN_MAX_AGE", "60")),
        conn_health_checks=True,
    )
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    # Wait for the write lock instead of failing immediately under concurrent joins.
    DATABASES["default"].setdefault("OPTIONS", {})["timeout"] = 20

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache is used for rate limiting. Database cache is shared across worker processes;
# run `python manage.py createcachetable` once per database.
CACHES = {
    "default": (
        {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "ensamien_cache"}
        if os.environ.get("CACHE_BACKEND", "db" if not DEBUG else "locmem") == "db"
        else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "ensamien"}
    )
}

AUTHENTICATION_BACKENDS = ["accounts.backends.EmailHostBackend"]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "live:host_dashboard"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Africa/Casablanca")
USE_I18N = False
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# --- Security -------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 12  # one presentation day
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
CSRF_FAILURE_VIEW = "config.views.csrf_failure"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

SECURE_SSL = env_bool("DJANGO_SECURE_SSL", not DEBUG)
SESSION_COOKIE_SECURE = SECURE_SSL
CSRF_COOKIE_SECURE = SECURE_SSL
SECURE_SSL_REDIRECT = SECURE_SSL
if SECURE_SSL:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "3600"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False  # do not affect other *.yassermansour.com apps
    SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]

# HSTS deliberately covers only this host: includeSubDomains/preload would affect every other
# *.yassermansour.com application, which this project must not touch.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

# --- Application settings -------------------------------------------------
ENSAMIEN = {
    "MAX_TEAMS": 10,
    "TEAM_NAME_MAX_LENGTH": 24,
    "SESSION_LIFETIME_HOURS": int(os.environ.get("SESSION_LIFETIME_HOURS", "12")),
    "PRESENCE_TIMEOUT_SECONDS": int(os.environ.get("PRESENCE_TIMEOUT_SECONDS", "10")),
    "PRESENCE_WRITE_INTERVAL_SECONDS": 3,
    "SUBMISSION_GRACE_SECONDS": 1.5,  # absorbs network latency at the deadline
    "DISPLAY_TOKEN_HOURS": int(os.environ.get("DISPLAY_TOKEN_HOURS", "12")),
    "RECOVERY_CODE_MINUTES": 10,
    "TEAM_COOKIE_NAME": "ensamien_team",
    # Only trust X-Forwarded-For when running behind a proxy that sets it (Heroku, nginx).
    "TRUST_X_FORWARDED_FOR": env_bool("TRUST_X_FORWARDED_FOR", SECURE_SSL),
    "SPEED_BONUS_ENABLED": env_bool("SPEED_BONUS_ENABLED", False),
    "SPEED_BONUS_MAX": int(os.environ.get("SPEED_BONUS_MAX", "50")),
    # Rate limits: (max failed attempts, window seconds)
    "LOGIN_LIMIT_PER_ACCOUNT": (5, 15 * 60),
    "LOGIN_LIMIT_PER_IP": (30, 15 * 60),
    # A whole classroom may share one NAT IP, so the per-IP join limit is generous;
    # the per-browser limit is what stops a single device from guessing codes.
    "JOIN_LIMIT_PER_IP": (60, 60),
    "JOIN_LIMIT_PER_CLIENT": (8, 60),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"level": "WARNING"},
        "django.server": {"level": os.environ.get("DJANGO_SERVER_LOG_LEVEL", "WARNING")},
    },
}
