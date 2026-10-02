import hashlib
import json
from functools import wraps

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET, require_POST
from redis.exceptions import RedisError

from . import presence, services
from .models import Command, Device, DevicePermission, QueueEntry


def api(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            if request.method == "POST":
                if len(request.body) > 8192:
                    raise services.ControlError("Request too large", 400)
                request.data = json.loads(request.body or "{}")
                if not isinstance(request.data, dict):
                    raise ValueError("Expected JSON object")
            return view(request, *args, **kwargs)
        except services.ControlError as exc:
            return JsonResponse({"error": str(exc)}, status=exc.status)
        except ValueError, KeyError, TypeError:
            return JsonResponse({"error": "Invalid request"}, status=400)
        except RedisError, ConnectionError:
            return JsonResponse({"error": "Control temporarily unavailable"}, status=503)
        except Device.DoesNotExist, Command.DoesNotExist:
            return JsonResponse({"error": "Not found"}, status=404)

    return wrapped


def session_data(request):
    return {
        "csrf_token": get_token(request),
        "authenticated": request.user.is_authenticated,
        "email": request.user.email if request.user.is_authenticated else None,
    }


@require_GET
@api
def session(request):
    return JsonResponse(session_data(request))


@require_POST
@api
def sign_in(request):
    # Caddy overwrites X-Forwarded-For. Trust it only behind the configured production proxy.
    address = request.META.get("REMOTE_ADDR", "unknown")
    if settings.SECURE_PROXY_SSL_HEADER:
        address = request.META.get("HTTP_X_FORWARDED_FOR", address).split(",")[-1].strip()
    key = f"{settings.CONTROL_REDIS_PREFIX}:login:{hashlib.sha256(address.encode()).hexdigest()}"
    redis = presence.client()
    count = redis.eval(
        "local n=redis.call('INCR',KEYS[1]); "
        "if n==1 then redis.call('EXPIRE',KEYS[1],300) end; return n",
        1,
        key,
    )
    if count > 20:
        raise services.ControlError("Too many login attempts; try again in five minutes", 429)
    user = authenticate(
        request, email=request.data.get("email"), password=request.data.get("password")
    )
    if not user:
        raise services.ControlError("Enter a Clemson email and the demo access password", 401)
    if not settings.CONTROL_DEMO_DEVICE_ID:
        raise services.ControlError("Demo device is not configured", 503)
    device = Device.objects.get(pk=settings.CONTROL_DEMO_DEVICE_ID, enabled=True)
    existing = QueueEntry.objects.filter(device=device, user=user).first()
    if existing and existing.session_key != request.session.session_key:
        raise services.ControlError("This email already has a queue place in another session")
    if not request.user.is_authenticated or request.user.pk != user.pk:
        login(request, user)
    DevicePermission.objects.get_or_create(device=device, user=user)
    services.join(device.id, user, request.session.session_key)
    return JsonResponse({**session_data(request), "device_id": str(device.id)})


@require_POST
@api
def sign_out(request):
    if request.user.is_authenticated:
        for entry in QueueEntry.objects.filter(
            user=request.user, session_key=request.session.session_key
        ):
            services.release(entry.device_id, request.user, request.session.session_key)
    logout(request)
    return JsonResponse(session_data(request))


@require_GET
@api
def devices(request):
    if not request.user.is_authenticated:
        raise services.ControlError("Sign in required", 401)
    ids = DevicePermission.objects.filter(user=request.user).values_list("device_id", flat=True)
    return JsonResponse(
        {
            "devices": [
                {"id": str(d.id), "name": d.name}
                for d in Device.objects.filter(id__in=ids, enabled=True)
            ]
        }
    )


@require_GET
@api
def status(request, device_id):
    return JsonResponse(services.snapshot(device_id, request.user, request.session.session_key))


@require_POST
@api
def queue_join(request, device_id):
    services.join(device_id, request.user, request.session.session_key)
    return JsonResponse(services.snapshot(device_id, request.user, request.session.session_key))


@require_POST
@api
def queue_leave(request, device_id):
    services.release(device_id, request.user, request.session.session_key)
    return JsonResponse(services.snapshot(device_id, request.user, request.session.session_key))


@require_POST
@api
def targets(request, device_id):
    command, created = services.submit(
        device_id, request.user, request.session.session_key, request.data
    )
    return JsonResponse({"command": command}, status=202 if created else 200)


@require_GET
@api
def command(request, device_id, command_id=None):
    services.permitted(device_id, request.user)
    query = Command.objects.filter(device_id=device_id)
    if command_id:
        result = query.get(pk=command_id)
    else:
        result = query.get(
            request_id=request.GET["request_id"], session_key=request.session.session_key
        )
    return JsonResponse({"command": services.command_json(result)})
