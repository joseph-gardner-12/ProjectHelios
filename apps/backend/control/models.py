import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    frame_version = models.CharField(max_length=80, default="dummy-enu-v1")
    enabled = models.BooleanField(default=True)
    connection_id = models.UUIDField(null=True, blank=True)
    channel_name = models.CharField(max_length=255, blank=True)
    revision = models.PositiveBigIntegerField(default=0)


class DeviceCredential(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    secret_hash = models.CharField(max_length=255)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class DevicePermission(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["device", "user"], name="device_user_unique")
        ]


class QueueEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    session_key = models.CharField(max_length=40)
    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField()
    released = models.BooleanField(default=False)

    class Meta:
        ordering = ["joined_at", "id"]
        constraints = [models.UniqueConstraint(fields=["device", "user"], name="one_queue_entry")]


class ControlLease(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    entry = models.OneToOneField(QueueEntry, on_delete=models.SET_NULL, null=True)
    started_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["device"], condition=Q(ended_at=None), name="one_live_lease"
            )
        ]


class Command(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    lease = models.ForeignKey(ControlLease, on_delete=models.PROTECT)
    session_key = models.CharField(max_length=40)
    request_id = models.UUIDField()
    connection_id = models.UUIDField()
    frame_version = models.CharField(max_length=80)
    target = models.JSONField()
    status = models.CharField(max_length=30, default="pending_ack")
    reason = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["device", "session_key", "request_id"], name="idempotent_submission"
            ),
            models.UniqueConstraint(
                fields=["device"],
                condition=Q(status__in=["pending_ack", "accepted"]),
                name="one_active_command",
            ),
        ]
