from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .readiness import database_ready, redis_ready


@never_cache
@require_GET
def health(request):
    return JsonResponse({"status": "ok", "service": "project-helios-backend"})


@never_cache
@require_GET
def ready(request):
    available = database_ready() and redis_ready()
    response = JsonResponse(
        {"status": "ok" if available else "unavailable"}, status=200 if available else 503
    )
    if settings.RELEASE_SHA:
        response["X-Helios-Release"] = settings.RELEASE_SHA
    return response
