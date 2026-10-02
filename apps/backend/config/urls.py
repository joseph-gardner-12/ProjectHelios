from django.contrib import admin
from django.urls import path

from core.views import health, ready

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/ready/", ready, name="ready"),
]
