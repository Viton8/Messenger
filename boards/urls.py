"""Template routes for boards (included under ``/boards/``)."""

from django.urls import path

from .views import board_page

app_name = "boards"

urlpatterns = [
    path("<uuid:board_id>/", board_page, name="board"),
]
