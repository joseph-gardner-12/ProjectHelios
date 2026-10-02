"""SQLite by default; set POSTGRES_HOST and REDIS_URL for integration work."""

import os

from .base import *  # noqa: F403
from .base import BASE_DIR, REDIS_URL
from .environment import postgres, redis_channels

SECRET_KEY = "django-insecure-helios-local-development-only"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "projecthelios.localhost"]
DATABASES = {
    "default": postgres()
    if os.environ.get("POSTGRES_HOST")
    else {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
}
CHANNEL_LAYERS = (
    redis_channels(REDIS_URL)
    if REDIS_URL
    else {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
)

CSRF_TRUSTED_ORIGINS = CONTROL_BROWSER_ORIGINS  # noqa: F405
