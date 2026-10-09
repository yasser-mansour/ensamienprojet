"""Credential helpers. Raw tokens are only ever held by the client; the database stores SHA-256 digests."""

import hashlib
import secrets


def hash_token(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_token():
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def new_join_code():
    """Cryptographically random six-digit numeric code (leading zeros allowed)."""
    return f"{secrets.randbelow(1_000_000):06d}"


RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I ambiguity


def new_recovery_code(length=6):
    return "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(length))
