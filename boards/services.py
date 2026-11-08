"""Server-side board metadata rules.

The browser is not trusted. Create, rename, lock, and delete are checked
here before the database is updated. Drawing sync is not implemented yet.
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from chat.group_services import (
    get_participant,
    require_admin,
    require_group,
    require_participant,
)
from chat.models import Message
from chat.services import broadcast_chat_message, broadcast_message_updated

from .models import Board

BOARD_TITLE_MAX = 80
GROUP_FULL_BOARDS = "This group already has the maximum number of boards."


def normalize_board_title(title):
    """Strip and require a board title of 1–80 characters.

    Args:
        title: Submitted title.

    Returns:
        str: Cleaned title.

    Raises:
        ValueError: When the title is empty or too long.
    """
    cleaned = " ".join((title or "").split())
    if not cleaned:
        raise ValueError("Board name is required.")
    if len(cleaned) > BOARD_TITLE_MAX:
        raise ValueError("Use %d characters or fewer." % BOARD_TITLE_MAX)
    return cleaned


def can_rename_or_delete_board(board, user):
    """Return True if ``user`` may change the title or delete ``board``."""
    participant = get_participant(board.chat, user)
    if participant is None:
        return False
    if participant.is_admin():
        return True
    return board.created_by_id == user.pk


def create_board(chat, user, title):
    """Create a board in a group and post a ``kind=board`` card.

    Args:
        chat: Group chat.
        user: Acting member.
        title: Board name.

    Returns:
        Board: The new board.

    Raises:
        PermissionError: When the user is not a member.
        ValueError: When the chat is not a group, the title is invalid, or
            the group is at the board cap.
    """
    require_group(chat)
    require_participant(chat, user)
    title = normalize_board_title(title)
    if Board.objects.filter(chat=chat).count() >= int(settings.BOARDS_MAX_PER_GROUP):
        raise ValueError(GROUP_FULL_BOARDS)
    with transaction.atomic():
        board = Board.objects.create(
            chat=chat,
            title=title,
            created_by=user,
            seq=0,
        )
        message = Message.objects.create(
            sender=user,
            chat=chat,
            content=title,
            kind=Message.KIND_BOARD,
            board=board,
        )
    message.sender = user
    broadcast_chat_message(message)
    return board


def list_boards(chat, user):
    """Return boards in ``chat`` for a member, oldest first."""
    require_group(chat)
    require_participant(chat, user)
    return (
        Board.objects.filter(chat=chat)
        .select_related("created_by")
        .order_by("created_at", "id")
    )


def update_board(board, user, *, title=None, is_locked=None):
    """Change title and/or lock. Field rights are checked before any save.

    A lock change requires admin or owner. A title change requires the
    creator or admin/owner. If lock is present and the caller is not an
    admin, nothing is written.

    Args:
        board: Stored board.
        user: Acting member.
        title: New title, or None to leave it.
        is_locked: New lock flag, or None to leave it.

    Returns:
        Board: The updated board.
    """
    require_group(board.chat)
    require_participant(board.chat, user)
    if is_locked is not None:
        require_admin(board.chat, user)
    if title is not None:
        if not can_rename_or_delete_board(board, user):
            raise PermissionError("You cannot rename this board.")
        board.title = normalize_board_title(title)
    if is_locked is not None:
        board.is_locked = bool(is_locked)
    if title is not None or is_locked is not None:
        board.save()
    return board


def delete_board(board, user):
    """Delete the board row and mark its chat card as Board deleted.

    Args:
        board: Stored board.
        user: Acting member.

    Raises:
        PermissionError: When the user may not delete the board.
    """
    require_group(board.chat)
    require_participant(board.chat, user)
    if not can_rename_or_delete_board(board, user):
        raise PermissionError("You cannot delete this board.")
    cards = list(
        Message.objects.filter(board=board, kind=Message.KIND_BOARD).select_related(
            "sender"
        )
    )
    now = timezone.now()
    from .broadcast import force_close_board

    force_close_board(board.pk)
    board.delete()
    for message in cards:
        message.board = None
        message.deleted_at = now
        message.save(update_fields=["deleted_at"])
        broadcast_message_updated(message)
