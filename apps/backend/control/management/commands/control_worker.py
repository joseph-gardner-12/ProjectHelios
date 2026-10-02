import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from control.services import tick


class Command(BaseCommand):
    help = "Reconcile control deadlines and queue leases; run as a supervised service"

    def handle(self, *args, **options):
        self.stdout.write(
            "Control worker started; checking deadlines and queue leases every second."
        )
        self.stdout.flush()
        try:
            while True:
                close_old_connections()
                tick()
                time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write("Control worker stopped.")
