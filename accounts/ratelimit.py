"""
Small fixed-window rate limiter built on Django's cache framework.

Only *failed* attempts are counted (login failures, invalid join codes), so a
legitimate classroom sharing one NAT address is not locked out by normal use.
"""

import hashlib
import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


def client_ip(request):
    """
    Client IP for rate limiting. Behind a trusted proxy (Heroku's router) the right-most
    X-Forwarded-For entry is the address the proxy saw; earlier entries are client-controlled.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded and settings.ENSAMIEN["TRUST_X_FORWARDED_FOR"]:
        return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _key(scope, ident):
    digest = hashlib.sha256(str(ident).encode()).hexdigest()[:32]
    return f"rl:{scope}:{digest}"


# A cache outage must never lock the host out or break joining in the middle of a class,
# so every cache error fails open and is logged.


def is_limited(scope, ident, limit):
    max_attempts, _window = limit
    try:
        return (cache.get(_key(scope, ident)) or 0) >= max_attempts
    except Exception:
        logger.exception("rate-limit cache unavailable (check); allowing request")
        return False


def register_failure(scope, ident, limit):
    _max_attempts, window = limit
    key = _key(scope, ident)
    try:
        if cache.add(key, 1, timeout=window):
            return 1
        try:
            return cache.incr(key)
        except ValueError:  # key expired between add() and incr()
            cache.set(key, 1, timeout=window)
            return 1
    except Exception:
        logger.exception("rate-limit cache unavailable (record)")
        return 0


def reset(scope, ident):
    try:
        cache.delete(_key(scope, ident))
    except Exception:
        logger.exception("rate-limit cache unavailable (reset)")
