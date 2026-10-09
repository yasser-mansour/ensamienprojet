from django.contrib import admin
from django.urls import include, path

from live.api import healthz

urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("host/", include("accounts.urls")),
    path("django-admin/", admin.site.urls),
    path("", include("live.urls")),
]
