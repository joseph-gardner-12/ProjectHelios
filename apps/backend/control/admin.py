from django.contrib import admin

from .models import Command, ControlLease, Device, DeviceCredential, DevicePermission, QueueEntry

admin.site.register([Device, DevicePermission])


@admin.register(DeviceCredential)
class CredentialAdmin(admin.ModelAdmin):
    fields = ("id", "device", "created_at", "revoked_at")
    readonly_fields = ("id", "device", "created_at")

    def has_add_permission(self, request):
        return False


@admin.register(Command, ControlLease, QueueEntry)
class AuditAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
