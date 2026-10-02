from django.contrib import admin
from django.urls import include, path

from core.views import health, ready

urlpatterns = [
    path("api/v1/", include("control.urls")),
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/ready/", ready, name="ready"),
]
