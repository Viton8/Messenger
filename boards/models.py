"""Board metadata and drawing objects for group chats."""

import uuid

from django.conf import settings
from django.db import models


class Board(models.Model):
    """A named whiteboard attached to one group chat."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey(
        "chat.Chat",
        on_delete=models.CASCADE,
        related_name="boards",
    )
    title = models.CharField(max_length=80)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_boards",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_locked = models.BooleanField(default=False)
    seq = models.PositiveIntegerField(
        default=0,
        help_text="Incremented once per accepted ops message.",
    )

    class Meta:
        verbose_name = "Board"
        verbose_name_plural = "Boards"
        indexes = [
            models.Index(fields=["chat", "created_at"]),
        ]
        ordering = ["created_at"]

    def __str__(self):
        return self.title


class BoardObject(models.Model):
    """One drawing object on a board. The client chooses the UUID."""

    id = models.UUIDField(primary_key=True, editable=False)
    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="board_objects",
    )
    type = models.CharField(max_length=16)
    data = models.JSONField(default=dict)
    z = models.IntegerField(default=0)
    deleted = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_board_objects",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Board object"
        verbose_name_plural = "Board objects"
        indexes = [
            models.Index(fields=["board", "deleted", "z"], name="boards_obj_live_z_idx"),
        ]
        ordering = ["z", "id"]

    def __str__(self):
        return f"{self.type} {self.id}"
