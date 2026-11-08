"""
URL configuration for messenger.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
"""

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.shortcuts import redirect
from django.urls import path, include


def home(request):
    """Send signed-in visitors to the chat inbox, otherwise to login."""
    if request.user.is_authenticated:
        return redirect("chat:inbox")
    return redirect("login")


urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("chat/", include("chat.urls")),
    path("boards/", include("boards.urls")),
    path("api/accounts/", include("accounts.api_urls")),
    path("api/chat/", include("chat.api_urls")),
]

# Static files: in DEBUG serve straight from app ``static/`` folders (no collectstatic needed).
# When DEBUG is off, use a real web server or WhiteNoise + collectstatic in production.
if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
else:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
