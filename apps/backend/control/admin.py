from django import forms
from django.contrib import admin
from django.contrib.auth.hashers import make_password

from .models import (
    Command,
    ControlLease,
    Device,
    DeviceCredential,
    DevicePermission,
    Machine,
    QueueEntry,
    RegistrationSettings,
)

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


class RegistrationForm(forms.ModelForm):
    registration_password = forms.CharField(
        required=False,
        max_length=256,
        widget=forms.PasswordInput,
        help_text="Set a new shared password, or leave blank to keep the current one.",
    )

    class Meta:
        model = RegistrationSettings
        fields = ("enabled",)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled") and not (
            cleaned.get("registration_password") or self.instance.password_hash
        ):
            self.add_error("registration_password", "Set a password to enable registration.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if password := self.cleaned_data.get("registration_password"):
            instance.password_hash = make_password(password)
        if commit:
            instance.save()
        return instance


@admin.register(RegistrationSettings)
class RegistrationAdmin(admin.ModelAdmin):
    form = RegistrationForm
    fields = ("enabled", "registration_password")

    def has_add_permission(self, request):
        return not RegistrationSettings.objects.exists() and super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ("name", "enabled", "legacy", "created_at", "last_connected_at")
    list_filter = ("enabled", "legacy")
    search_fields = ("name",)
    fields = ("id", "name", "enabled", "credential", "legacy", "created_at", "last_connected_at")
    readonly_fields = ("id", "credential", "legacy", "created_at", "last_connected_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
