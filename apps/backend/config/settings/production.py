"""Fail closed when the production environment is incomplete."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .environment import hostnames, origins, postgres, redis_channels, required

SECRET_KEY = required("DJANGO_SECRET_KEY")
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a strong, production-only secret")
DEBUG = False
ALLOWED_HOSTS = hostnames("DJANGO_ALLOWED_HOSTS")
CORS_ALLOWED_ORIGINS = origins("DJANGO_FRONTEND_ORIGINS")
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS
CORS_ALLOW_CREDENTIALS = True
DATABASES = {"default": postgres()}
REDIS_URL = required("REDIS_URL")
CHANNEL_LAYERS = redis_channels(REDIS_URL)

# Daphne is reachable only through Caddy, which overwrites forwarded headers.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# Initial rollout scopes HSTS to this API host; enrolling all subdomains or the
# browser preload list requires a separate domain-wide commitment.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None

CONTROL_BROWSER_ORIGINS = CORS_ALLOWED_ORIGINS
