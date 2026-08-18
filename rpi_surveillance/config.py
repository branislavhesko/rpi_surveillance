"""Shared configuration loaded from a gitignored ``.env`` at the repo root.

Dependency-free so it can be imported from anywhere without pulling in the
camera/inference stack. Real environment variables always win over ``.env``.
"""
import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_env() -> None:
    """Populate ``os.environ`` from the repo-root ``.env`` (non-overriding)."""
    if not _ENV_PATH.exists():
        return
    try:
        for line in _ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    except Exception as e:  # pragma: no cover - best-effort loader
        logger.warning(f"Could not read .env: {e}")


# Load once at import so any consumer sees the values.
load_env()


def get_users() -> dict[str, str]:
    """Return the login map from ``APP_USERS`` (``user:pass,user2:pass2``).

    Falls back to a single ``admin:admin`` dev account (with a warning) so the
    app stays usable before a ``.env`` is configured.
    """
    users: dict[str, str] = {}
    for pair in os.environ.get("APP_USERS", "").split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        user, _, password = pair.partition(":")
        users[user.strip()] = password
    if not users:
        logger.warning(
            "APP_USERS not set in .env — falling back to insecure default admin/admin"
        )
        return {"admin": "admin"}
    return users


def get_storage_secret() -> str:
    """Session-cookie signing key from ``STORAGE_SECRET``.

    If unset, generate an ephemeral random secret (with a warning). That logs
    everyone out on restart, but never ships a known/guessable key.
    """
    secret = os.environ.get("STORAGE_SECRET", "").strip()
    if not secret:
        logger.warning(
            "STORAGE_SECRET not set in .env — using a random ephemeral secret "
            "(sessions will not survive a restart)"
        )
        return secrets.token_hex(32)
    return secret
