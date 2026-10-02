"""Bounded, fresh dependency probes, independent of request transactions."""

from django.conf import settings
from django.db import DatabaseError, connections
from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry


def database_ready():
    probe = connections["default"].copy(alias="readiness")
    if probe.vendor == "postgresql":
        probe.settings_dict["OPTIONS"] = {
            **probe.settings_dict.get("OPTIONS", {}),
            "connect_timeout": 2,
            "options": "-c statement_timeout=2000 -c lock_timeout=2000",
        }
    try:
        with probe.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)
    except DatabaseError:
        return False
    finally:
        probe.close()


def redis_ready():
    if not settings.REDIS_URL:
        return False
    try:
        with Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry=Retry(NoBackoff(), 0),
        ) as client:
            return client.ping()
    except RedisError, OSError, ValueError:
        return False
