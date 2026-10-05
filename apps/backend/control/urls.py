from django.urls import path

from . import views

urlpatterns = [
    path("machines/register/", views.register_machine),
    path("session/", views.session),
    path("login/", views.sign_in),
    path("logout/", views.sign_out),
    path("devices/", views.devices),
    path("devices/<uuid:device_id>/", views.status),
    path("devices/<uuid:device_id>/queue/", views.status),
    path("devices/<uuid:device_id>/queue/join/", views.queue_join),
    path("devices/<uuid:device_id>/queue/leave/", views.queue_leave),
    path("devices/<uuid:device_id>/targets/", views.targets),
    path("devices/<uuid:device_id>/commands/", views.command),
    path("devices/<uuid:device_id>/commands/<uuid:command_id>/", views.command),
]
