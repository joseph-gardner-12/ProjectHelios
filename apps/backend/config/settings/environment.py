"""Small, explicit environment contract shared by local and production settings."""

import ipaddress
import os
import re
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} is required")
    return value


def hostnames(name):
    hosts = [value.strip() for value in required(name).split(",")]
    for host in hosts:
        try:
            ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            if len(host) > 253 or not all(
                re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                for label in host.split(".")
            ):
                raise ImproperlyConfigured(f"{name} must contain exact hostnames, without ports")
    return hosts


def origins(name):
    values = [value.strip() for value in required(name).split(",")]
    for value in values:
        try:
            url = urlsplit(value)
            valid = (
                url.scheme == "https"
                and url.hostname
                and "*" not in url.netloc
                and not url.username
                and not url.password
                and not url.path
                and not url.query
                and not url.fragment
                and (url.port is None or 1 <= url.port <= 65535)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ImproperlyConfigured(f"{name} must contain HTTPS origins without paths")
    return values


def postgres():
    host = required("POSTGRES_HOST")
    try:
        port = int(os.environ.get("POSTGRES_PORT", "5432"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError as error:
        raise ImproperlyConfigured("POSTGRES_PORT must be a valid port") from error
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": required("POSTGRES_DB"),
        "USER": required("POSTGRES_USER"),
        "PASSWORD": required("POSTGRES_PASSWORD"),
        "HOST": host,
        "PORT": port,
        "CONN_MAX_AGE": 0,
        "OPTIONS": {
            "connect_timeout": 3,
            "sslmode": "disable" if host in {"127.0.0.1", "localhost", "::1"} else "require",
        },
    }


def redis_channels(url):
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme in {"redis", "rediss"}
            and parsed.hostname
            and not parsed.query
            and not parsed.fragment
            and (not parsed.path or re.fullmatch(r"/\d+", parsed.path))
            and (parsed.port is None or 1 <= parsed.port <= 65535)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ImproperlyConfigured("REDIS_URL must be a redis:// or rediss:// URL")
    return {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [{"address": url, "socket_connect_timeout": 2, "socket_timeout": 2}],
                "prefix": "helios",
                "capacity": 100,
                "expiry": 60,
            },
        }
    }
