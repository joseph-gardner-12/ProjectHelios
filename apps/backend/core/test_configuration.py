"""Production config is evaluated in fresh processes, without Django's settings cache."""

import json
import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase

PRODUCTION_ENV = {
    "DJANGO_SETTINGS_MODULE": "config.settings.production",
    "DJANGO_SECRET_KEY": "test-only-secret-abcdefghijklmnopqrstuvwxyz-0123456789",
    "DJANGO_ALLOWED_HOSTS": "api.projecthelios.dev",
    "DJANGO_FRONTEND_ORIGINS": "https://www.projecthelios.dev,https://projecthelios.dev",
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_DB": "helios",
    "POSTGRES_USER": "helios",
    "POSTGRES_PASSWORD": "test-only-password",
    "REDIS_URL": "redis://127.0.0.1:6379/0",
}


class ProductionConfigurationTests(SimpleTestCase):
    def evaluate(self, overrides=None, missing=None):
        environment = {key: value for key, value in os.environ.items() if key in {"PATH", "HOME"}}
        environment.update(PRODUCTION_ENV)
        environment.update(overrides or {})
        if missing:
            environment.pop(missing)
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "import json; from django.conf import settings as s; "
                "print(json.dumps({'debug': s.DEBUG, 'db': s.DATABASES['default']['ENGINE'], "
                "'cookies': [s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE], "
                "'hosts': s.ALLOWED_HOSTS, 'cors': s.CORS_ALLOWED_ORIGINS, "
                "'csrf': s.CSRF_TRUSTED_ORIGINS, "
                "'max_age': s.DATABASES['default']['CONN_MAX_AGE']}))",
            ],
            cwd=settings.BASE_DIR,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_production_uses_explicit_secure_configuration(self):
        result = self.evaluate()
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertFalse(values["debug"])
        self.assertEqual(values["db"], "django.db.backends.postgresql")
        self.assertEqual(values["cookies"], [True, True])
        self.assertEqual(values["hosts"], ["api.projecthelios.dev"])
        self.assertEqual(values["cors"], values["csrf"])
        self.assertEqual(values["max_age"], 0)

    def test_every_required_value_fails_closed(self):
        for name in PRODUCTION_ENV.keys() - {"DJANGO_SETTINGS_MODULE"}:
            with self.subTest(variable=name):
                result = self.evaluate(missing=name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{name} is required", result.stderr)

    def test_invalid_values_are_rejected_without_echoing_secrets(self):
        invalid = {
            "DJANGO_SECRET_KEY": ["short", "x" * 60, "django-insecure-" + "abcdefghi" * 8],
            "DJANGO_ALLOWED_HOSTS": [
                "*",
                ".projecthelios.dev",
                "https://api.projecthelios.dev",
                "",
            ],
            "DJANGO_FRONTEND_ORIGINS": [
                "http://www.projecthelios.dev",
                "https://*.projecthelios.dev",
                "https://www.projecthelios.dev/",
                "https://user:password@www.projecthelios.dev",
                "https://www.projecthelios.dev:invalid",
            ],
            "POSTGRES_PORT": ["zero", "0", "65536"],
            "REDIS_URL": ["http://localhost", "redis://", "redis://localhost/not-a-db"],
        }
        for name, values in invalid.items():
            for value in values:
                with self.subTest(variable=name, value=value):
                    result = self.evaluate({name: value})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("ImproperlyConfigured", result.stderr)
                    self.assertNotIn(PRODUCTION_ENV["POSTGRES_PASSWORD"], result.stderr)

    def test_local_settings_still_start_without_external_services(self):
        result = subprocess.run(
            [sys.executable, "manage.py", "check"],
            cwd=settings.BASE_DIR,
            env={key: value for key, value in os.environ.items() if key in {"PATH", "HOME"}},
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
