"""WebSocket URL routes for boards."""

from django.urls import re_path

from .consumers import BoardConsumer

websocket_urlpatterns = [
    re_path(
        r"ws/boards/(?P<board_id>[0-9a-f-]+)/$",
        BoardConsumer.as_asgi(),
    ),
]
