"""Fast local tests; CI supplies PostgreSQL and Redis for integration tests."""

from .local import *  # noqa: F403

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
