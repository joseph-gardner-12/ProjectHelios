"""All control decisions serialize on the device row; Redis is never a durable queue."""

import hashlib
import logging
import math
import secrets
import uuid
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from . import presence
from .models import Command, ControlLease, Device, DeviceCredential, DevicePermission, QueueEntry
from .protocol import ACTIVE, coordinates, identifier, validate_message

log = logging.getLogger(__name__)


class ControlError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def group(device_id):
    return f"device.{device_id}"


def changed(device):
    device.revision += 1
    device.save()


def notify(device_id):
    try:
        async_to_sync(get_channel_layer().group_send)(group(device_id), {"type": "refresh"})
    except Exception:
        log.warning("Redis notification unavailable device=%s", device_id)


def envelope(device, kind):
    return {
        "version": 1,
        "type": kind,
        "device_id": str(device.id),
        "connection_id": str(device.connection_id) if device.connection_id else None,
        "frame_version": device.frame_version,
        "timestamp": timezone.now().isoformat(),
    }


def command_json(command):
    if not command:
        return None
    return {
        "id": str(command.id),
        "request_id": str(command.request_id),
        "target": command.target,
        "status": command.status,
        "reason": command.reason,
        "created_at": command.created_at.isoformat(),
        "expires_at": command.expires_at.isoformat(),
    }


def permitted(device_id, user):
    if (
        not user.is_authenticated
        or not DevicePermission.objects.filter(
            device_id=device_id, user=user, device__enabled=True
        ).exists()
    ):
        raise ControlError("Device access denied", 403)


def live(device, state, now):
    return bool(
        device.enabled
        and device.connection_id
        and state
        and state.get("connection_id") == str(device.connection_id)
        and now.timestamp() - state.get("received_at", 0) < 5
    )


def fresh(device, state, now):
    return live(device, state, now) and now.timestamp() - state.get("position_at", 0) < 2


def invalidate(device, reason):
    now = timezone.now()
    for command in Command.objects.filter(device=device, status__in=ACTIVE):
        command.status = "unconfirmed" if command.status == "pending_ack" else "interrupted"
        command.reason = reason
        command.finished_at = now
        command.save()
        log.info("command=%s status=%s reason=%s", command.id, command.status, reason)
    old_channel = device.channel_name
    device.connection_id = None
    device.channel_name = ""
    changed(device)
    if old_channel:

        def close_old():
            try:
                async_to_sync(get_channel_layer().send)(old_channel, {"type": "replaced"})
            except Exception:
                pass  # Pi heartbeat watchdog still stops motion.

        transaction.on_commit(close_old)


def reconcile_locked(device, state, now):
    active = Command.objects.filter(device=device, status__in=ACTIVE).first()
    reason = None
    if device.connection_id and not live(device, state, now):
        reason = "Connection lost"
    elif active and active.status == "pending_ack" and active.expires_at <= now:
        reason = "Acknowledgment timed out; delivery unconfirmed"
    elif active and active.accepted_at and now - active.accepted_at >= timedelta(seconds=30):
        reason = "Execution timed out"
    if reason:
        invalidate(device, reason)
        active = None
    lease = (
        ControlLease.objects.filter(device=device, ended_at=None).select_related("entry").first()
    )
    if lease:
        entry = lease.entry
        release = (
            not entry
            or entry.released
            or lease.expires_at <= now
            or now - entry.last_seen >= timedelta(seconds=15)
        )
        if release and not active:
            lease.ended_at = now
            lease.save()
            if entry:
                entry.delete()
            lease = None
            changed(device)
    waiting = QueueEntry.objects.filter(device=device)
    if lease and lease.entry_id:
        waiting = waiting.exclude(pk=lease.entry_id)
    expired = waiting.filter(last_seen__lte=now - timedelta(seconds=15))
    if expired.exists() or waiting.filter(released=True).exists():
        expired.delete()
        waiting.filter(released=True).delete()
        changed(device)
    if not lease and not active and fresh(device, state, now) and state.get("state") == "idle":
        # A newly queued HTTP session is not yet present; only promote a socket-confirmed entry.
        for entry in waiting.filter(released=False).order_by("joined_at", "id"):
            if presence.client().exists(browser_key(device.id, entry.session_key)):
                lease = ControlLease.objects.create(
                    device=device,
                    entry=entry,
                    started_at=now,
                    expires_at=now + timedelta(minutes=5),
                )
                changed(device)
                log.info("control turn started device=%s lease=%s", device.id, lease.id)
                break
    return lease


def browser_key(device_id, session_key):
    digest = hashlib.sha256(session_key.encode()).hexdigest()
    return f"{presence.key(device_id)}:browser:{digest}"


def browser_seen(device_id, user, session_key):
    permitted(device_id, user)
    presence.client().set(browser_key(device_id, session_key), "1", ex=2)
    QueueEntry.objects.filter(device_id=device_id, user=user, session_key=session_key).update(
        last_seen=timezone.now()
    )


def join(device_id, user, session_key):
    permitted(device_id, user)
    with transaction.atomic():
        device = Device.objects.select_for_update().get(pk=device_id)
        reconcile_locked(device, presence.read(device_id), timezone.now())
        existing = QueueEntry.objects.filter(device=device, user=user).first()
        if existing and existing.session_key != session_key:
            raise ControlError("This email already has a queue place in another session")
        if not existing:
            QueueEntry.objects.create(
                device=device, user=user, session_key=session_key, last_seen=timezone.now()
            )
            changed(device)
    notify(device_id)


def release(device_id, user, session_key):
    permitted(device_id, user)
    with transaction.atomic():
        device = Device.objects.select_for_update().get(pk=device_id)
        QueueEntry.objects.filter(device=device, user=user, session_key=session_key).update(
            released=True
        )
        changed(device)
        reconcile_locked(device, presence.read(device_id), timezone.now())
    notify(device_id)


def snapshot(device_id, user, session_key):
    permitted(device_id, user)
    with transaction.atomic():
        device = Device.objects.select_for_update().get(pk=device_id)
        state = presence.read(device_id)
        now = timezone.now()
        lease = reconcile_locked(device, state, now)
        entry = QueueEntry.objects.filter(device=device, user=user, session_key=session_key).first()
        owns = bool(lease and entry and lease.entry_id == entry.id)
        command = Command.objects.filter(device=device).order_by("-created_at").first()
        usable = fresh(device, state, now)
        queue_position = None
        if entry and not owns:
            entries = list(
                QueueEntry.objects.filter(device=device, released=False).values_list(
                    "id", flat=True
                )
            )
            if entry.id in entries:
                queue_position = entries.index(entry.id) + 1 - bool(lease)
        return {
            **envelope(device, "snapshot"),
            "revision": device.revision,
            "name": device.name,
            "health": "fresh" if usable else ("stale" if live(device, state, now) else "offline"),
            "position": state.get("position") if state else None,
            "position_at": state.get("position_at") if state else None,
            "sequence": state.get("sequence", -1) if state else -1,
            "source": "dummy",
            "command": command_json(command),
            "queue": {
                "position": queue_position,
                "joined": bool(entry),
                "controller": owns,
                "lease_id": str(lease.id) if owns else None,
                "expires_at": lease.expires_at.isoformat() if lease else None,
                "releasing": bool(entry and entry.released),
            },
            "can_send": bool(
                owns
                and not entry.released
                and lease.expires_at > now
                and usable
                and state.get("state") == "idle"
                and (not command or command.status not in ACTIVE)
            ),
        }


def submit(device_id, user, session_key, data):
    permitted(device_id, user)
    try:
        target = coordinates(data["target"])
        request_id = identifier(data["request_id"])
        lease_id = identifier(data["lease_id"])
        frame = data["frame_version"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ControlError("Invalid target request", 400) from exc
    with transaction.atomic():
        device = Device.objects.select_for_update().get(pk=device_id)
        existing = Command.objects.filter(
            device=device, session_key=session_key, request_id=request_id
        ).first()
        if existing:
            if (
                existing.target != target
                or existing.frame_version != frame
                or str(existing.lease_id) != lease_id
            ):
                raise ControlError("Request ID reused with different payload")
            return command_json(existing), False
        state = presence.read(device_id)
        now = timezone.now()
        lease = reconcile_locked(device, state, now)
        # Do not raise inside the transaction after reconciliation: persist expired state first.
        valid = (
            lease
            and str(lease.id) == lease_id
            and lease.entry
            and lease.entry.user_id == user.id
            and lease.entry.session_key == session_key
            and not lease.entry.released
            and lease.expires_at > now
            and fresh(device, state, now)
            and state.get("state") == "idle"
            and not Command.objects.filter(device=device, status__in=ACTIVE).exists()
            and frame == device.frame_version
        )
        if valid:
            command = Command.objects.create(
                device=device,
                user=user,
                lease=lease,
                session_key=session_key,
                request_id=request_id,
                connection_id=device.connection_id,
                frame_version=frame,
                target=target,
                created_at=now,
                expires_at=now + timedelta(seconds=3),
            )
            changed(device)
    if not valid:
        raise ControlError("Control turn, idle device, fresh telemetry and matching frame required")
    try:
        async_to_sync(get_channel_layer().send)(
            device.channel_name, {"type": "command.dispatch", "command_id": str(command.id)}
        )
    except Exception:
        disconnect(device_id, command.connection_id, "Dispatch unavailable")
        command.refresh_from_db()
    notify(device_id)
    return command_json(command), True


def issue_credential(device):
    secret = secrets.token_urlsafe(32)
    credential = DeviceCredential.objects.create(device=device, secret_hash=make_password(secret))
    return f"{credential.id}.{secret}"


def authenticate_pi(token):
    try:
        key, secret = token.split(".", 1)
        credential = DeviceCredential.objects.select_related("device").get(
            pk=identifier(key), revoked_at=None, device__enabled=True
        )
        return credential if check_password(secret, credential.secret_hash) else None
    except ValueError, DeviceCredential.DoesNotExist:
        return None


def connect_pi(credential_id, channel_name):
    credential = DeviceCredential.objects.get(
        pk=credential_id, revoked_at=None, device__enabled=True
    )
    with transaction.atomic():
        device = Device.objects.select_for_update().get(pk=credential.device_id)
        invalidate(device, "Connection replaced")
        device.connection_id = uuid.uuid4()
        device.channel_name = channel_name
        changed(device)
        presence.write(
            device.id,
            {
                "connection_id": str(device.connection_id),
                "received_at": timezone.now().timestamp(),
                "sequence": -1,
                "ready": False,
                "position_at": 0,
            },
        )
        result = {**envelope(device, "setup"), "telemetry_hz": 5}
    notify(device.id)
    return result


def disconnect(device_id, connection_id, reason="Connection lost"):
    with transaction.atomic():
        device = Device.objects.select_for_update().get(pk=device_id)
        if str(device.connection_id) == str(connection_id):
            invalidate(device, reason)
    notify(device_id)


def check_connection(device_id, connection_id, credential_id):
    with transaction.atomic():
        device = Device.objects.select_for_update().get(pk=device_id)
        state = presence.read(device.id)
        valid = (
            str(device.connection_id) == str(connection_id)
            and DeviceCredential.objects.filter(
                pk=credential_id, device=device, revoked_at=None
            ).exists()
            and live(device, state, timezone.now())
        )
        if not valid:
            if str(device.connection_id) == str(connection_id):
                invalidate(device, "Connection or credential expired")
            return None
        return envelope(device, "heartbeat")


def dispatch_message(device_id, connection_id, command_id):
    with transaction.atomic():
        device = Device.objects.select_for_update().get(pk=device_id)
        state = presence.read(device.id)
        reconcile_locked(device, state, timezone.now())
        command = Command.objects.filter(
            pk=command_id, device=device, connection_id=connection_id, status="pending_ack"
        ).first()
        if not command or str(device.connection_id) != str(connection_id):
            return None
        return {
            **envelope(device, "target"),
            "command_id": str(command.id),
            "expires_at": command.expires_at.isoformat(),
            "target": command.target,
        }


def receive_pi(device_id, connection_id, data):
    with transaction.atomic():
        device = Device.objects.select_for_update().get(pk=device_id)
        if str(device.connection_id) != str(connection_id):
            raise ControlError("Superseded connection")
        validate_message(data, device, connection_id)
        state = presence.read(device_id)
        now = timezone.now()
        if not live(device, state, now):
            raise ControlError("Presence expired")
        state["received_at"] = now.timestamp()
        kind = data["type"]
        if kind == "ready":
            state["ready"] = True
        elif kind == "position":
            if not state.get("ready") or data["sequence"] <= state.get("sequence", -1):
                return
            if not state.get("position_at") and data["state"] != "idle":
                raise ValueError("First position must be idle")
            state.update(
                position=data["position"],
                sequence=data["sequence"],
                position_at=now.timestamp(),
                source_timestamp=data["timestamp"],
                state=data["state"],
            )
            completed = data.get("completed_command_id")
            if completed:
                arrive(device, state, completed, now)
        elif kind == "ack":
            command = Command.objects.filter(
                pk=data["command_id"], device=device, connection_id=connection_id
            ).first()
            if command and command.status == "pending_ack":
                if command.expires_at <= now:
                    invalidate(device, "Late acknowledgment")
                else:
                    command.status = "accepted" if data["accepted"] else "rejected"
                    command.accepted_at = now if data["accepted"] else None
                    command.finished_at = None if data["accepted"] else now
                    command.reason = str(data.get("reason", ""))[:120]
                    command.save()
                    changed(device)
        elif kind == "arrival":
            arrive(device, state, data["command_id"], now)
        presence.write(device.id, state)
    notify(device_id)


def arrive(device, state, command_id, now):
    command = Command.objects.filter(
        pk=command_id, device=device, connection_id=device.connection_id, status="accepted"
    ).first()
    if (
        not command
        or state.get("state") != "idle"
        or not fresh(device, state, now)
        or math.dist(
            list(command.target[k] for k in "xyz"), list(state["position"][k] for k in "xyz")
        )
        > 0.01
        or now - command.accepted_at < timedelta(seconds=0.5)
    ):
        return
    command.status = "arrived"
    command.finished_at = now
    command.save()
    changed(device)
    log.info("command=%s status=arrived", command.id)


def tick():
    for device_id in Device.objects.values_list("id", flat=True):
        try:
            with transaction.atomic():
                device = Device.objects.select_for_update().get(pk=device_id)
                before = device.revision
                reconcile_locked(device, presence.read(device_id), timezone.now())
            if before != device.revision:
                notify(device_id)
        except Exception:
            log.exception("Lifecycle reconciliation failed device=%s", device_id)
            with transaction.atomic():
                device = Device.objects.select_for_update().get(pk=device_id)
                if device.connection_id:
                    invalidate(device, "Control infrastructure unavailable")
