from django.test import SimpleTestCase
from django.urls import reverse


class HealthTests(SimpleTestCase):
    def test_health_is_public_and_returns_json(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"status": "ok", "service": "project-helios-backend"}
        )

    def test_health_rejects_writes(self):
        self.assertEqual(self.client.post(reverse("health")).status_code, 405)
