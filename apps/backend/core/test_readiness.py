from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase, override_settings

from core.readiness import database_ready, redis_ready


class ReadinessTests(SimpleTestCase):
    @override_settings(RELEASE_SHA="1" * 40)
    def test_readiness_identifies_the_running_release(self):
        with (
            patch("core.views.database_ready", return_value=True),
            patch("core.views.redis_ready", return_value=True),
        ):
            response = self.client.get("/api/ready/")
        self.assertEqual(response["X-Helios-Release"], "1" * 40)

    def test_dependencies_must_both_be_available(self):
        for database, redis, code in [(True, True, 200), (False, True, 503), (True, False, 503)]:
            with self.subTest(database=database, redis=redis):
                with (
                    patch("core.views.database_ready", return_value=database),
                    patch("core.views.redis_ready", return_value=redis),
                ):
                    response = self.client.get("/api/ready/")
                self.assertEqual(response.status_code, code)
                self.assertEqual(
                    response.json(), {"status": "ok" if code == 200 else "unavailable"}
                )
                self.assertIn("no-store", response["Cache-Control"])

    def test_health_never_checks_dependencies(self):
        with (
            patch("core.views.database_ready") as database,
            patch("core.views.redis_ready") as redis,
        ):
            self.assertEqual(self.client.get("/api/health/").status_code, 200)
            database.assert_not_called()
            redis.assert_not_called()

    def test_ready_rejects_writes_without_probing(self):
        with patch("core.views.database_ready") as database:
            self.assertEqual(self.client.post("/api/ready/").status_code, 405)
            database.assert_not_called()

    def test_database_connection_failure_is_sanitized_and_closed(self):
        with patch("core.readiness.connections") as connections:
            probe = connections["default"].copy.return_value
            probe.cursor.side_effect = OperationalError("secret connection details")
            self.assertFalse(database_ready())
            probe.close.assert_called_once()

    @override_settings(REDIS_URL="")
    def test_unconfigured_redis_is_not_reported_ready(self):
        self.assertFalse(redis_ready())

    @override_settings(REDIS_URL="redis://127.0.0.1:1/0")
    def test_unreachable_redis_returns_unavailable(self):
        self.assertFalse(redis_ready())


@override_settings(
    ALLOWED_HOSTS=["api.projecthelios.dev"],
    CORS_ALLOWED_ORIGINS=["https://www.projecthelios.dev"],
    CORS_ALLOW_CREDENTIALS=True,
    CSRF_TRUSTED_ORIGINS=["https://www.projecthelios.dev"],
    SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
)
class OriginAndProxyTests(SimpleTestCase):
    def test_only_known_browser_origins_get_cors_headers(self):
        for origin, permitted in [
            ("https://www.projecthelios.dev", True),
            ("https://other.dev", False),
        ]:
            response = self.client.get(
                "/api/health/",
                HTTP_HOST="api.projecthelios.dev",
                HTTP_ORIGIN=origin,
                HTTP_X_FORWARDED_PROTO="https",
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual("Access-Control-Allow-Origin" in response, permitted)

    def test_invalid_host_is_rejected(self):
        self.assertEqual(self.client.get("/api/health/", HTTP_HOST="other.dev").status_code, 400)

    def test_http_redirects_but_forwarded_https_does_not_loop(self):
        self.assertEqual(
            self.client.get("/api/health/", HTTP_HOST="api.projecthelios.dev").status_code, 301
        )
        self.assertEqual(
            self.client.get(
                "/api/health/", HTTP_HOST="api.projecthelios.dev", HTTP_X_FORWARDED_PROTO="https"
            ).status_code,
            200,
        )
