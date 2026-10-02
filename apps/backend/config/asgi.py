import os

from channels.routing import ProtocolTypeRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django_application = get_asgi_application()


async def reject_websocket(scope, receive, send):
    """Reject upgrades until authenticated device/browser endpoints are implemented."""
    await receive()
    await send({"type": "websocket.close", "code": 1008})


application = ProtocolTypeRouter({"http": django_application, "websocket": reject_websocket})
