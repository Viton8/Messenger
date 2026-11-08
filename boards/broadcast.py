"""Channel-layer helpers to fan board events and close sockets."""

from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def board_group_name(board_id):
    return f"board_{board_id}"


def board_user_group_name(user_id):
    return f"boarduser_{user_id}"


def _send(group, payload):
    layer = get_channel_layer()
    if not layer:
        return
    try:
        async_to_sync(layer.group_send)(group, payload)
    except Exception:
        logger.warning("Board broadcast failed group=%s", group, exc_info=True)


def fanout_board(board_id, payload):
    """Send a typed event to everyone on the board."""
    _send(board_group_name(board_id), payload)


def force_close_board(board_id):
    """Close every socket on this board."""
    fanout_board(board_id, {"type": "board_force_close"})


def force_close_user_boards(user_id, chat_id=None):
    """Close this user's board sockets, optionally limited to one chat."""
    payload = {"type": "board_force_close"}
    if chat_id is not None:
        payload["chat_id"] = str(chat_id)
    _send(board_user_group_name(user_id), payload)
