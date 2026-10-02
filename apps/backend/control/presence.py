"""Transient state must fail closed when Redis is unavailable."""

import json

from django.conf import settings
from redis import Redis


def client():
    if not settings.REDIS_URL:
        raise ConnectionError("Control requires REDIS_URL")
    return Redis.from_url(
        settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1, decode_responses=True
    )


def key(device_id):
    return f"{settings.CONTROL_REDIS_PREFIX}:device:{device_id}"


def read(device_id):
    raw = client().get(key(device_id))
    return json.loads(raw) if raw else None


def write(device_id, data):
    client().set(key(device_id), json.dumps(data), ex=6)


def clear(device_id):
    client().delete(key(device_id))
