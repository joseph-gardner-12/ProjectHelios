import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from django.conf import settings
from django.core.asgi import get_asgi_application
from django.urls import path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django_application = get_asgi_application()

from control.consumers import BrowserConsumer, PiConsumer  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_application,
        "websocket": URLRouter(
            [
                path("ws/v1/pi/", PiConsumer.as_asgi()),
                path(
                    "ws/v1/devices/<uuid:device_id>/",
                    OriginValidator(
                        AuthMiddlewareStack(BrowserConsumer.as_asgi()),
                        settings.CONTROL_BROWSER_ORIGINS,
                    ),
                ),
            ]
        ),
    }
)
