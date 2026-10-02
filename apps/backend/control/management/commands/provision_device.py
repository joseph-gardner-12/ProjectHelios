from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from control.models import Device
from control.services import issue_credential


class Command(BaseCommand):
    help = "Create a demo device and write a new credential to a private file"

    def add_arguments(self, parser):
        parser.add_argument("--name", default="Helios dummy Pi")
        parser.add_argument("--device-id")
        parser.add_argument("--credential-file", required=True)

    def handle(self, *args, **options):
        path = Path(options["credential_file"])
        if path.exists():
            raise CommandError("Credential file already exists")
        device = (
            Device.objects.get(pk=options["device_id"])
            if options["device_id"]
            else Device.objects.create(name=options["name"])
        )
        with path.open("x") as file:
            path.chmod(0o600)
            file.write(issue_credential(device) + "\n")
        self.stdout.write(f"CONTROL_DEMO_DEVICE_ID={device.id}")
