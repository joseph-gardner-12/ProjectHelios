from django.db import migrations


def preserve_computers(apps, schema_editor):
    alias = schema_editor.connection.alias
    Credential = apps.get_model("control", "DeviceCredential")
    Machine = apps.get_model("control", "Machine")
    for credential in Credential.objects.using(alias).select_related("device").iterator():
        machine, created = Machine.objects.using(alias).get_or_create(
            credential_id=credential.id,
            defaults={
                "name": f"{credential.device.name[:70]} (legacy {str(credential.id)[:8]})",
                "legacy": True,
                "created_at": credential.created_at,
            },
        )
        if created:
            Machine.objects.using(alias).filter(pk=machine.pk).update(
                created_at=credential.created_at
            )
    apps.get_model("control", "RegistrationSettings").objects.using(alias).get_or_create(pk=1)
    apps.get_model("control", "ConnectionSlot").objects.using(alias).get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("control", "0002_computer_registration")]
    # Reversal must not touch the existing Device or DeviceCredential records.
    operations = [migrations.RunPython(preserve_computers, migrations.RunPython.noop)]
